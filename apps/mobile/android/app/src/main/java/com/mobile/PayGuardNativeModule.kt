package com.mobile

import android.media.AudioAttributes
import android.media.SoundPool
import android.os.Build
import android.os.Handler
import android.os.Looper
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.speech.tts.TextToSpeech
import android.speech.tts.UtteranceProgressListener
import android.util.Base64
import androidx.biometric.BiometricManager
import androidx.biometric.BiometricManager.Authenticators.BIOMETRIC_STRONG
import androidx.biometric.BiometricManager.Authenticators.DEVICE_CREDENTIAL
import androidx.biometric.BiometricPrompt
import androidx.core.content.ContextCompat
import androidx.fragment.app.FragmentActivity
import com.facebook.react.bridge.Arguments
import com.facebook.react.bridge.Promise
import com.facebook.react.bridge.ReactApplicationContext
import com.facebook.react.bridge.ReactContextBaseJavaModule
import com.facebook.react.bridge.ReactMethod
import java.security.KeyPairGenerator
import java.security.KeyStore
import java.security.PrivateKey
import java.security.Signature
import java.security.spec.ECGenParameterSpec
import java.util.Locale

/**
 * PayGuard's own Android helpers:
 *  - a signing key in the Android Keystore that only unlocks after fingerprint,
 *    face (strong) or the phone's PIN/pattern; the server checks its signatures,
 *  - short, distinct sounds for payment events,
 *  - speaking replies aloud (TextToSpeech) for the live voice mode.
 */
class PayGuardNativeModule(private val reactContext: ReactApplicationContext) :
  ReactContextBaseJavaModule(reactContext) {

  override fun getName() = "PayGuardNative"

  private val keyAlias = "payguard_confirm_key"
  private val mainHandler = Handler(Looper.getMainLooper())

  // Strong biometrics or the phone's own PIN / pattern / password.
  // Weak face unlock cannot unlock a Keystore key, so it is not offered.
  private val authenticators =
    if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) BIOMETRIC_STRONG or DEVICE_CREDENTIAL
    else BIOMETRIC_STRONG

  // ---------- security ----------

  @ReactMethod
  fun securityStatus(promise: Promise) {
    val result = Arguments.createMap()
    val code = BiometricManager.from(reactContext).canAuthenticate(authenticators)
    result.putBoolean("available", code == BiometricManager.BIOMETRIC_SUCCESS)
    result.putString(
      "reason",
      when (code) {
        BiometricManager.BIOMETRIC_SUCCESS -> "ok"
        BiometricManager.BIOMETRIC_ERROR_NONE_ENROLLED -> "Set a fingerprint or screen lock PIN on this phone first."
        BiometricManager.BIOMETRIC_ERROR_NO_HARDWARE -> "This phone has no fingerprint or screen lock support."
        else -> "Fingerprint or PIN is not available right now."
      },
    )
    result.putBoolean("hasKey", loadKeyStore().containsAlias(keyAlias))
    promise.resolve(result)
  }

  /** Public key (base64 X.509) to register with the server. Creates the key once. */
  @ReactMethod
  fun getPublicKey(promise: Promise) {
    try {
      val keyStore = loadKeyStore()
      if (!keyStore.containsAlias(keyAlias)) createKey()
      val publicKey = loadKeyStore().getCertificate(keyAlias).publicKey
      promise.resolve(Base64.encodeToString(publicKey.encoded, Base64.NO_WRAP))
    } catch (error: Exception) {
      promise.reject("key_error", "Could not create the PayGuard security key.", error)
    }
  }

  /** Remove the key, e.g. after logging out or when the server lost it. */
  @ReactMethod
  fun resetKey(promise: Promise) {
    try {
      loadKeyStore().deleteEntry(keyAlias)
      promise.resolve(true)
    } catch (error: Exception) {
      promise.reject("key_error", "Could not reset the security key.", error)
    }
  }

  /**
   * Show the fingerprint / PIN prompt, then sign `payload` with the key.
   * Resolves with a base64 DER ECDSA signature.
   */
  @ReactMethod
  fun signWithAuth(payload: String, title: String, subtitle: String, promise: Promise) {
    val activity = reactContext.currentActivity as? FragmentActivity
    if (activity == null) {
      promise.reject("no_activity", "PayGuard is not on screen.")
      return
    }

    val signature: Signature
    try {
      val keyStore = loadKeyStore()
      if (!keyStore.containsAlias(keyAlias)) createKey()
      val privateKey = loadKeyStore().getKey(keyAlias, null) as PrivateKey
      signature = Signature.getInstance("SHA256withECDSA")
      signature.initSign(privateKey)
    } catch (error: Exception) {
      // The phone's lock screen changed and the old key was wiped: start again.
      try { loadKeyStore().deleteEntry(keyAlias) } catch (_: Exception) {}
      promise.reject("key_invalid", "Your phone's security changed. Please set up PayGuard security again.", error)
      return
    }

    mainHandler.post {
      val prompt = BiometricPrompt(
        activity,
        ContextCompat.getMainExecutor(reactContext),
        object : BiometricPrompt.AuthenticationCallback() {
          override fun onAuthenticationSucceeded(result: BiometricPrompt.AuthenticationResult) {
            try {
              val signer = result.cryptoObject?.signature ?: signature
              signer.update(payload.toByteArray(Charsets.UTF_8))
              promise.resolve(Base64.encodeToString(signer.sign(), Base64.NO_WRAP))
            } catch (error: Exception) {
              promise.reject("sign_error", "Could not sign the confirmation.", error)
            }
          }

          override fun onAuthenticationError(code: Int, message: CharSequence) {
            promise.reject("cancelled", message.toString())
          }
        },
      )

      val info = BiometricPrompt.PromptInfo.Builder()
        .setTitle(title)
        .setSubtitle(subtitle)
        .setAllowedAuthenticators(authenticators)
        .apply {
          // A Cancel button is only allowed when the phone PIN is not offered.
          if (authenticators == BIOMETRIC_STRONG) setNegativeButtonText("Cancel")
        }
        .build()

      prompt.authenticate(info, BiometricPrompt.CryptoObject(signature))
    }
  }

  private fun loadKeyStore(): KeyStore = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }

  private fun createKey() {
    val builder = KeyGenParameterSpec.Builder(keyAlias, KeyProperties.PURPOSE_SIGN)
      .setAlgorithmParameterSpec(ECGenParameterSpec("secp256r1"))
      .setDigests(KeyProperties.DIGEST_SHA256)
      .setUserAuthenticationRequired(true)
      // A new fingerprint added later wipes the key, so a thief cannot add theirs.
      .setInvalidatedByBiometricEnrollment(true)

    if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
      // 0 seconds: every single signature needs a fresh fingerprint or PIN.
      builder.setUserAuthenticationParameters(0, KeyProperties.AUTH_BIOMETRIC_STRONG or KeyProperties.AUTH_DEVICE_CREDENTIAL)
    }

    KeyPairGenerator.getInstance(KeyProperties.KEY_ALGORITHM_EC, "AndroidKeyStore").apply {
      initialize(builder.build())
      generateKeyPair()
    }
  }

  // ---------- encrypted storage (the login stays until logout) ----------

  private val storageAlias = "payguard_storage_key"
  private val prefs by lazy { reactContext.getSharedPreferences("payguard_secure", android.content.Context.MODE_PRIVATE) }

  private fun storageKey(): javax.crypto.SecretKey {
    val keyStore = loadKeyStore()
    (keyStore.getKey(storageAlias, null) as? javax.crypto.SecretKey)?.let { return it }
    val generator = javax.crypto.KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore")
    generator.init(
      KeyGenParameterSpec.Builder(storageAlias, KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT)
        .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
        .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
        .setKeySize(256)
        .build(),
    )
    return generator.generateKey()
  }

  /** Encrypt with a key that never leaves the phone's secure hardware. */
  @ReactMethod
  fun saveSecret(name: String, value: String, promise: Promise) {
    try {
      val cipher = javax.crypto.Cipher.getInstance("AES/GCM/NoPadding")
      cipher.init(javax.crypto.Cipher.ENCRYPT_MODE, storageKey())
      val sealed = cipher.iv + cipher.doFinal(value.toByteArray(Charsets.UTF_8))
      prefs.edit().putString(name, Base64.encodeToString(sealed, Base64.NO_WRAP)).apply()
      promise.resolve(true)
    } catch (error: Exception) {
      promise.reject("storage_error", "Could not save securely.", error)
    }
  }

  @ReactMethod
  fun loadSecret(name: String, promise: Promise) {
    try {
      val stored = prefs.getString(name, null) ?: return promise.resolve(null)
      val sealed = Base64.decode(stored, Base64.NO_WRAP)
      val cipher = javax.crypto.Cipher.getInstance("AES/GCM/NoPadding")
      cipher.init(
        javax.crypto.Cipher.DECRYPT_MODE,
        storageKey(),
        javax.crypto.spec.GCMParameterSpec(128, sealed.copyOfRange(0, 12)),
      )
      promise.resolve(String(cipher.doFinal(sealed.copyOfRange(12, sealed.size)), Charsets.UTF_8))
    } catch (error: Exception) {
      // Unreadable (e.g. app data restored on another phone): treat as logged out.
      prefs.edit().remove(name).apply()
      promise.resolve(null)
    }
  }

  @ReactMethod
  fun deleteSecret(name: String, promise: Promise) {
    prefs.edit().remove(name).apply()
    promise.resolve(true)
  }

  // ---------- sounds ----------

  // PayGuard's own chimes (res/raw/pg_*.wav, made by tools/make_sounds.py).
  private val soundPool: SoundPool by lazy {
    SoundPool.Builder()
      .setMaxStreams(3)
      .setAudioAttributes(
        AudioAttributes.Builder()
          .setUsage(AudioAttributes.USAGE_ASSISTANCE_SONIFICATION)
          .setContentType(AudioAttributes.CONTENT_TYPE_SONIFICATION)
          .build(),
      )
      .build()
  }

  private val soundIds: Map<String, Int> by lazy {
    mapOf(
      "payment_sent" to R.raw.pg_payment_sent,
      "money_received" to R.raw.pg_money_received,
      "refund_done" to R.raw.pg_money_received,
      "request_sent" to R.raw.pg_request_sent,
      "failed" to R.raw.pg_warning,
      "warning" to R.raw.pg_warning,
      "confirm_needed" to R.raw.pg_confirm_needed,
      "listening" to R.raw.pg_listening,
      "stopped" to R.raw.pg_stopped,
      "unlocked" to R.raw.pg_unlocked,
    ).mapValues { (_, resource) -> soundPool.load(reactContext, resource, 1) }
  }

  /** Load the sounds early so the first one plays without delay. */
  override fun initialize() {
    super.initialize()
    soundIds
  }

  /** Short sounds that are easy to tell apart without looking at the screen. */
  @ReactMethod
  fun playSound(name: String) {
    val id = soundIds[name] ?: return
    soundPool.play(id, 1f, 1f, 1, 0, 1f)
  }

  // ---------- speech ----------

  private var tts: TextToSpeech? = null
  private var ttsReady = false
  private val pendingSpeech = mutableMapOf<String, Promise>()

  private fun ensureTts(onReady: () -> Unit) {
    if (tts != null && ttsReady) {
      onReady()
      return
    }
    tts = TextToSpeech(reactContext) { status ->
      ttsReady = status == TextToSpeech.SUCCESS
      tts?.setOnUtteranceProgressListener(object : UtteranceProgressListener() {
        override fun onStart(utteranceId: String) {}
        override fun onDone(utteranceId: String) { pendingSpeech.remove(utteranceId)?.resolve(true) }
        @Deprecated("Deprecated in Java")
        override fun onError(utteranceId: String) { pendingSpeech.remove(utteranceId)?.resolve(false) }
        override fun onStop(utteranceId: String, interrupted: Boolean) { pendingSpeech.remove(utteranceId)?.resolve(false) }
      })
      onReady()
    }
  }

  /** Speak text aloud; resolves when finished, so the app can listen again. */
  @ReactMethod
  fun speak(text: String, language: String, promise: Promise) {
    ensureTts {
      val engine = tts
      if (engine == null || !ttsReady) {
        promise.resolve(false)
        return@ensureTts
      }
      engine.language = if (language == "ta") Locale("ta", "IN") else Locale.US
      val id = "pg_${System.nanoTime()}"
      pendingSpeech[id] = promise
      engine.speak(text, TextToSpeech.QUEUE_FLUSH, null, id)
    }
  }

  @ReactMethod
  fun stopSpeaking() {
    tts?.stop()
    pendingSpeech.values.forEach { it.resolve(false) }
    pendingSpeech.clear()
  }

  override fun invalidate() {
    tts?.shutdown()
    tts = null
    soundPool.release()
    super.invalidate()
  }
}
