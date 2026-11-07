import React, {useState} from 'react';
import {AccessibilityInfo, Text, TouchableOpacity, View} from 'react-native';

import {api} from '../api';
import {playSound} from '../native';
import {t} from '../session';
import {ui} from '../theme';
import PinField from './PinField';

type Props = {
  token: string;
  tamil: boolean;
  // Changing an existing PIN asks for the current one.
  change?: boolean;
  onDone: () => void;
  onCancel?: () => void;
};

/** Set (or change) the PayGuard PIN asked before money is sent or the balance is shown. */
const PinSetup = ({token, tamil, change, onDone, onCancel}: Props) => {
  const [oldPin, setOldPin] = useState('');
  const [pin, setPin] = useState('');
  const [again, setAgain] = useState('');
  const [message, setMessage] = useState('');
  const [busy, setBusy] = useState(false);

  const say = (text: string) => {
    setMessage(text);
    AccessibilityInfo.announceForAccessibility(text);
  };

  const save = async () => {
    if (pin.length < 4) {
      return say(t(tamil, 'Please type 4 to 6 digits.', '4 முதல் 6 இலக்கங்கள் தட்டச்சு செய்யுங்கள்.'));
    }
    if (pin !== again) {
      setAgain('');
      return say(
        t(tamil, 'The two PINs are different. Please type it again.',
          'இரண்டு PIN-களும் வேறுபடுகின்றன. மீண்டும் தட்டச்சு செய்யுங்கள்.'),
      );
    }
    setBusy(true);
    try {
      await api('/api/security/pin', token, {body: {pin, old_pin: change ? oldPin || null : null}});
      playSound('unlocked');
      AccessibilityInfo.announceForAccessibility(t(tamil, 'PayGuard PIN saved.', 'PayGuard PIN சேமிக்கப்பட்டது.'));
      onDone();
    } catch (error) {
      setPin('');
      setAgain('');
      playSound('failed');
      say(error instanceof Error ? error.message : 'Could not save the PIN.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <View style={ui.card}>
      <Text style={ui.title} accessibilityRole="header">
        {change
          ? t(tamil, 'Change your PayGuard PIN', 'PayGuard PIN-ஐ மாற்று')
          : t(tamil, 'Set your PayGuard PIN', 'உங்கள் PayGuard PIN-ஐ அமையுங்கள்')}
      </Text>
      <Text style={ui.body}>
        {t(tamil,
          'You will type this PIN, and use your fingerprint, before sending money, refunding or seeing your balance. Use 4 to 6 digits that nobody else knows.',
          'பணம் அனுப்ப, பணம் திருப்ப அல்லது இருப்பைப் பார்க்க இந்த PIN-உம் கைரேகையும் தேவை. 4 முதல் 6 இலக்கங்கள் பயன்படுத்துங்கள்.')}
      </Text>
      {change && (
        <PinField label={t(tamil, 'Current PIN', 'தற்போதைய PIN')} value={oldPin} onChange={setOldPin} autoFocus />
      )}
      <PinField label={t(tamil, 'New PIN', 'புதிய PIN')} value={pin} onChange={setPin} autoFocus={!change} />
      <PinField
        label={t(tamil, 'Type the new PIN again', 'புதிய PIN-ஐ மீண்டும்')}
        value={again}
        onChange={setAgain}
        onDone={save}
      />
      {message ? (
        <Text style={ui.error} accessibilityLiveRegion="assertive">
          {message}
        </Text>
      ) : null}
      <TouchableOpacity
        onPress={save}
        disabled={busy}
        accessibilityRole="button"
        accessibilityState={{disabled: busy, busy}}
        style={[ui.primaryButton, busy && ui.disabled]}>
        <Text style={ui.primaryButtonText}>
          {busy ? t(tamil, 'Saving…', 'சேமிக்கிறது…') : t(tamil, 'Save PIN', 'PIN சேமி')}
        </Text>
      </TouchableOpacity>
      {onCancel && (
        <TouchableOpacity onPress={onCancel} accessibilityRole="button" style={ui.secondaryButton}>
          <Text style={ui.secondaryButtonText}>{t(tamil, 'Cancel', 'ரத்து')}</Text>
        </TouchableOpacity>
      )}
    </View>
  );
};

export default PinSetup;
