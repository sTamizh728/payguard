import React, {useEffect, useState} from 'react';
import {AccessibilityInfo, StyleSheet, Text, TouchableOpacity, View} from 'react-native';

import {PendingAction} from '../api';
import {playSound} from '../native';
import {colors} from '../theme';
import PinField from './PinField';

type Props = {
  action: PendingAction;
  busy: boolean;
  // The PayGuard PIN typed in the box ('' for PayPal checkout).
  onConfirm: (pin: string) => void;
  onCancel: () => void;
};

/** The only place money can move: fingerprint / face / PIN, then the server checks it. */
const ConfirmBox = ({action, busy, onConfirm, onCancel}: Props) => {
  const warnings = action.warnings ?? [];
  // Scam guard cooling-off. The server enforces it too; this only shows it.
  const [wait, setWait] = useState(action.wait_seconds ?? 0);
  const [pin, setPin] = useState('');

  useEffect(() => {
    setWait(action.wait_seconds ?? 0);
    setPin('');
  }, [action.id, action.wait_seconds]);

  useEffect(() => {
    if (wait <= 0) {
      return;
    }
    const timer = setTimeout(() => {
      const next = wait - 1;
      setWait(next);
      if (next === 0) {
        AccessibilityInfo.announceForAccessibility('You can confirm now if you are sure.');
        playSound('confirm_needed');
      }
    }, 1000);
    return () => clearTimeout(timer);
  }, [wait]);

  const checkout = action.type === 'checkout';
  const needsPin = !checkout && pin.length < 4;
  const locked = busy || wait > 0 || needsPin;
  const press = () => {
    const typed = pin;
    setPin(''); // never keep the PIN around after one try
    onConfirm(typed);
  };

  return (
    <View style={[styles.box, warnings.length > 0 && styles.risky]}>
      {warnings.length > 0 && (
        <View accessible accessibilityLiveRegion="polite">
          <Text style={styles.warnTitle} accessibilityRole="header">
            ⚠️ Scam check: {warnings.length} warning signs
          </Text>
          {warnings.map(reason => (
            <Text key={reason} style={styles.warnLine}>
              • {reason}
            </Text>
          ))}
          <Text style={styles.warnAdvice}>
            If someone is rushing you or you don't know them, cancel.
          </Text>
        </View>
      )}

      <Text style={styles.text} accessibilityRole="header">
        {action.summary}?
      </Text>
      <Text style={styles.hint}>
        {checkout
          ? 'You will pay in PayPal checkout.'
          : wait > 0
            ? `Confirm unlocks in ${wait} seconds.`
            : 'Type your PayGuard PIN, then confirm with your fingerprint, face or phone PIN.'}
      </Text>
      {!checkout && (
        <PinField label="PayGuard PIN" value={pin} onChange={setPin} onDone={() => !locked && press()} />
      )}
      <View style={styles.row}>
        <TouchableOpacity
          onPress={press}
          disabled={locked}
          accessibilityRole="button"
          accessibilityLabel={
            checkout
              ? `Pay with PayPal: ${action.summary}`
              : wait > 0
                ? `Confirm, locked for ${wait} seconds`
                : needsPin
                  ? 'Confirm. Type your PayGuard PIN first'
                  : `Confirm with fingerprint or PIN: ${action.summary}`
          }
          accessibilityState={{disabled: locked, busy}}
          style={[styles.button, styles.yes, locked && styles.disabled]}>
          <Text style={styles.yesText}>
            {busy
              ? 'Please wait...'
              : checkout
                ? 'Pay with PayPal'
                : wait > 0
                  ? `🔒 ${wait}s`
                  : '🔒 Confirm'}
          </Text>
        </TouchableOpacity>
        <TouchableOpacity
          onPress={onCancel}
          disabled={busy}
          accessibilityRole="button"
          accessibilityState={{disabled: busy}}
          style={[styles.button, styles.no]}>
          <Text style={styles.noText}>Cancel</Text>
        </TouchableOpacity>
      </View>
    </View>
  );
};

const styles = StyleSheet.create({
  box: {
    borderWidth: 2,
    borderColor: '#F59E0B',
    backgroundColor: colors.warnBg,
    borderRadius: 14,
    padding: 16,
    marginVertical: 10,
  },
  risky: {
    borderColor: colors.bad,
    backgroundColor: colors.badBg,
  },
  warnTitle: {
    color: colors.bad,
    fontSize: 18,
    fontWeight: '800',
    marginBottom: 6,
  },
  warnLine: {
    color: colors.ink,
    fontSize: 16,
    lineHeight: 23,
  },
  warnAdvice: {
    color: colors.bad,
    fontSize: 15,
    fontWeight: '700',
    marginTop: 8,
    marginBottom: 12,
  },
  text: {
    color: colors.ink,
    fontSize: 18,
    fontWeight: '800',
  },
  hint: {
    color: colors.muted,
    fontSize: 14,
    marginTop: 4,
    marginBottom: 12,
  },
  row: {
    flexDirection: 'row',
    gap: 10,
    marginTop: 12,
  },
  button: {
    flex: 1,
    paddingVertical: 15,
    borderRadius: 12,
    alignItems: 'center',
  },
  yes: {
    backgroundColor: colors.good,
  },
  yesText: {
    color: '#FFFFFF',
    fontSize: 17,
    fontWeight: '800',
  },
  no: {
    backgroundColor: colors.card,
    borderWidth: 1,
    borderColor: colors.line,
  },
  noText: {
    color: colors.ink,
    fontSize: 17,
    fontWeight: '700',
  },
  disabled: {
    opacity: 0.6,
  },
});

export default ConfirmBox;
