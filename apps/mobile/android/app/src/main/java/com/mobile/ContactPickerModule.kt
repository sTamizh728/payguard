package com.mobile

import android.app.Activity
import android.content.Intent
import android.provider.ContactsContract.CommonDataKinds.Email
import com.facebook.react.bridge.Arguments
import com.facebook.react.bridge.BaseActivityEventListener
import com.facebook.react.bridge.Promise
import com.facebook.react.bridge.ReactApplicationContext
import com.facebook.react.bridge.ReactContextBaseJavaModule
import com.facebook.react.bridge.ReactMethod

/**
 * Opens the phone's own contact picker (only contacts with an email) and returns the
 * chosen name + email. The system picker grants access to that one contact only, so
 * PayGuard never needs permission to read the whole contact book.
 */
class ContactPickerModule(private val reactContext: ReactApplicationContext) :
  ReactContextBaseJavaModule(reactContext) {

  private var pending: Promise? = null

  private val listener = object : BaseActivityEventListener() {
    override fun onActivityResult(activity: Activity, requestCode: Int, resultCode: Int, data: Intent?) {
      if (requestCode != REQUEST_CODE) return
      val promise = pending ?: return
      pending = null
      val uri = data?.data
      if (resultCode != Activity.RESULT_OK || uri == null) {
        promise.resolve(null) // the person backed out
        return
      }
      try {
        reactContext.contentResolver
          .query(uri, arrayOf(Email.ADDRESS, Email.DISPLAY_NAME_PRIMARY), null, null, null)
          ?.use { cursor ->
            if (cursor.moveToFirst()) {
              val result = Arguments.createMap()
              result.putString("email", cursor.getString(0) ?: "")
              result.putString("name", cursor.getString(1) ?: "")
              promise.resolve(result)
              return
            }
          }
        promise.resolve(null)
      } catch (error: Exception) {
        promise.reject("PICK_FAILED", "Could not read that contact.")
      }
    }
  }

  init {
    reactContext.addActivityEventListener(listener)
  }

  override fun getName() = "ContactPicker"

  @ReactMethod
  fun pickEmail(promise: Promise) {
    val activity = reactContext.currentActivity
    if (activity == null) {
      promise.reject("NO_ACTIVITY", "PayGuard is not on screen.")
      return
    }
    pending?.resolve(null)
    pending = promise
    try {
      activity.startActivityForResult(Intent(Intent.ACTION_PICK, Email.CONTENT_URI), REQUEST_CODE)
    } catch (error: Exception) {
      pending = null
      promise.reject("NO_PICKER", "This phone has no contact picker.")
    }
  }

  companion object {
    private const val REQUEST_CODE = 4711
  }
}
