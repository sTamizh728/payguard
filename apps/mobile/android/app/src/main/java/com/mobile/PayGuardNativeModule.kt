package com.mobile

import android.media.AudioManager
import android.media.ToneGenerator
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

  // ---------- sounds ----------

  private val tones by lazy { ToneGenerator(AudioManager.STREAM_MUSIC, 85) }

  /** Short sounds that are easy to tell apart without looking at the screen. */
  @ReactMethod
  fun playSound(name: String) {
    val steps: List<Pair<Int, Int>> = when (name) {
      // rising two notes: money left your wallet
      "payment_sent" -> listOf(ToneGenerator.TONE_DTMF_5 to 120, ToneGenerator.TONE_DTMF_9 to 220)
      // three quick bright notes: money came back / received
      "refund_done", "money_received" -> listOf(
        ToneGenerator.TONE_DTMF_9 to 90, ToneGenerator.TONE_DTMF_6 to 90, ToneGenerator.TONE_DTMF_D to 200,
      )
      // single soft beep: a request was sent and is waiting
      "request_sent" -> listOf(ToneGenerator.TONE_PROP_BEEP to 200)
      // low double buzz: something failed, nothing moved
      "failed" -> listOf(ToneGenerator.TONE_PROP_NACK to 400)
      // confirm prompt appears
      "confirm_needed" -> listOf(ToneGenerator.TONE_PROP_PROMPT to 250)
      // microphone on / off in live voice mode
      "listening" -> listOf(ToneGenerator.TONE_PROP_BEEP2 to 120)
      "stopped" -> listOf(ToneGenerator.TONE_PROP_ACK to 150)
      else -> emptyList()
    }

    var delay = 0L
    for ((tone, ms) in steps) {
      mainHandler.postDelayed({ tones.startTone(tone, ms) }, delay)
      delay += ms + 40L
    }
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
    super.invalidate()
  }
}
