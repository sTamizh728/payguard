package com.mobile

import android.content.Context
import android.media.AudioAttributes
import android.media.AudioDeviceInfo
import android.media.AudioFormat
import android.media.AudioManager
import android.media.AudioRecord
import android.media.AudioTrack
import android.media.MediaRecorder
import android.media.audiofx.AcousticEchoCanceler
import android.media.audiofx.NoiseSuppressor
import android.os.Build
import com.facebook.react.bridge.ReactApplicationContext
import com.facebook.react.bridge.ReactContextBaseJavaModule
import com.facebook.react.bridge.ReactMethod
import com.facebook.react.modules.core.DeviceEventManagerModule
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import okio.ByteString
import okio.ByteString.Companion.toByteString
import org.json.JSONObject
import java.util.concurrent.TimeUnit

/**
 * Live voice: streams the microphone (16 kHz PCM) to PayGuard's server over a
 * WebSocket and plays the spoken replies (24 kHz PCM) on the loudspeaker.
 * Events from the server go to JavaScript as "PayGuardLive" (JSON strings).
 */
class LiveVoiceModule(private val reactContext: ReactApplicationContext) :
  ReactContextBaseJavaModule(reactContext) {

  override fun getName() = "PayGuardLive"

  private val inRate = 16000
  private val outRate = 24000

  private var socket: WebSocket? = null
  private var recorder: AudioRecord? = null
  private var player: AudioTrack? = null
  private var echo: AcousticEchoCanceler? = null
  private var noise: NoiseSuppressor? = null
  @Volatile private var running = false
  @Volatile private var muted = false
  // Don't send the microphone while PayGuard is speaking (+300 ms), so it
  // can never hear itself and interrupt its own answer.
  @Volatile private var speakingUntil = 0L

  private val audio by lazy { reactContext.getSystemService(Context.AUDIO_SERVICE) as AudioManager }

  private fun emit(json: String) {
    reactContext
      .getJSModule(DeviceEventManagerModule.RCTDeviceEventEmitter::class.java)
      .emit("PayGuardLive", json)
  }

  private fun emitType(type: String, message: String? = null) {
    emit(JSONObject().put("type", type).apply { if (message != null) put("message", message) }.toString())
  }

  // Needed by NativeEventEmitter on the JavaScript side.
  @ReactMethod fun addListener(eventName: String) {}
  @ReactMethod fun removeListeners(count: Double) {}

  /** Connect and start talking. The microphone permission must already be granted. */
  @ReactMethod
  fun start(url: String, token: String) {
    if (running) return
    running = true
    muted = false
    speakingUntil = 0L

    val client = OkHttpClient.Builder()
      .readTimeout(0, TimeUnit.MILLISECONDS)
      .pingInterval(20, TimeUnit.SECONDS)
      .build()
    val request = Request.Builder().url(url).header("Authorization", "Bearer $token").build()

    socket = client.newWebSocket(request, object : WebSocketListener() {
      override fun onOpen(webSocket: WebSocket, response: Response) {
        try {
          startAudio(webSocket)
        } catch (error: Exception) {
          emitType("end", "The microphone could not start.")
          stopAll()
        }
      }

      override fun onMessage(webSocket: WebSocket, bytes: ByteString) {
        val data = bytes.toByteArray()
        val ms = data.size * 1000L / (outRate * 2)
        val now = System.currentTimeMillis()
        speakingUntil = maxOf(speakingUntil, now) + ms
        player?.write(data, 0, data.size)
      }

      override fun onMessage(webSocket: WebSocket, text: String) {
        if (text.contains("\"interrupted\"")) {
          // The person spoke: stop the voice at once.
          player?.let { it.pause(); it.flush(); it.play() }
          speakingUntil = 0L
        }
        emit(text)
      }

      override fun onClosed(webSocket: WebSocket, code: Int, reason: String) {
        if (code == 4401) emitType("end", "Please log in again.")
        stopAll()
        emitType("closed")
      }

      override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
        if (response?.code == 403 || response?.code == 401) emitType("end", "Please log in again.")
        else if (running) emitType("end", "The live connection was lost.")
        stopAll()
        emitType("closed")
      }
    })
  }

  private fun startAudio(ws: WebSocket) {
    // Phone-call style audio: echo cancelling, loudspeaker on.
    audio.mode = AudioManager.MODE_IN_COMMUNICATION
    if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
      audio.availableCommunicationDevices
        .firstOrNull { it.type == AudioDeviceInfo.TYPE_BUILTIN_SPEAKER }
        ?.let { audio.setCommunicationDevice(it) }
    } else {
      @Suppress("DEPRECATION")
      audio.isSpeakerphoneOn = true
    }

    val outSize = AudioTrack.getMinBufferSize(outRate, AudioFormat.CHANNEL_OUT_MONO, AudioFormat.ENCODING_PCM_16BIT)
    player = AudioTrack.Builder()
      .setAudioAttributes(
        AudioAttributes.Builder()
          .setUsage(AudioAttributes.USAGE_VOICE_COMMUNICATION)
          .setContentType(AudioAttributes.CONTENT_TYPE_SPEECH)
          .build(),
      )
      .setAudioFormat(
        AudioFormat.Builder()
          .setSampleRate(outRate)
          .setChannelMask(AudioFormat.CHANNEL_OUT_MONO)
          .setEncoding(AudioFormat.ENCODING_PCM_16BIT)
          .build(),
      )
      .setBufferSizeInBytes(maxOf(outSize, outRate * 2))
      .setTransferMode(AudioTrack.MODE_STREAM)
      .build()
      .also { it.play() }

    val inSize = AudioRecord.getMinBufferSize(inRate, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT)
    @Suppress("MissingPermission")
    val rec = AudioRecord(
      MediaRecorder.AudioSource.VOICE_COMMUNICATION,
      inRate,
      AudioFormat.CHANNEL_IN_MONO,
      AudioFormat.ENCODING_PCM_16BIT,
      maxOf(inSize, inRate * 2),
    )
    recorder = rec
    if (AcousticEchoCanceler.isAvailable()) echo = AcousticEchoCanceler.create(rec.audioSessionId)?.apply { enabled = true }
    if (NoiseSuppressor.isAvailable()) noise = NoiseSuppressor.create(rec.audioSessionId)?.apply { enabled = true }
    rec.startRecording()

    Thread {
      val chunk = ByteArray(inRate * 2 / 10) // 100 ms
      val silence = ByteArray(chunk.size)
      while (running) {
        val read = rec.read(chunk, 0, chunk.size)
        if (read <= 0) continue
        val quiet = muted || System.currentTimeMillis() < speakingUntil + 300
        // Send silence instead of nothing, so the server's voice detection keeps time.
        ws.send((if (quiet) silence else chunk).toByteString(0, read))
      }
    }.apply { name = "PayGuardLiveMic"; start() }

    emitType("listening")
  }

  /** Pause the microphone, e.g. while the Confirm box waits for the fingerprint. */
  @ReactMethod
  fun setMuted(value: Boolean) {
    muted = value
  }

  /** Let PayGuard say a result, e.g. after the fingerprint confirm. */
  @ReactMethod
  fun say(text: String) {
    socket?.send(JSONObject().put("type", "say").put("text", text).toString())
  }

  @ReactMethod
  fun stop() {
    socket?.send(JSONObject().put("type", "stop").toString())
    socket?.close(1000, "bye")
    stopAll()
  }

  private fun stopAll() {
    if (!running) return
    running = false
    try { recorder?.stop() } catch (_: Exception) {}
    recorder?.release(); recorder = null
    echo?.release(); echo = null
    noise?.release(); noise = null
    try { player?.stop() } catch (_: Exception) {}
    player?.release(); player = null
    socket = null
    if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) audio.clearCommunicationDevice()
    else @Suppress("DEPRECATION") { audio.isSpeakerphoneOn = false }
    audio.mode = AudioManager.MODE_NORMAL
  }

  override fun invalidate() {
    stop()
    super.invalidate()
  }
}
