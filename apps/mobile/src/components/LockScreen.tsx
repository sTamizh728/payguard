import React, {useCallback, useEffect, useState} from 'react';
import {StyleSheet, Text, TouchableOpacity, View} from 'react-native';

import {playSound, unlock} from '../native';
import {t} from '../session';
import {colors} from '../theme';

type Props = {
  tamil: boolean;
  onUnlocked: () => void;
  onLogout: () => void;
};

/** Covers the whole app until fingerprint, face or phone PIN. */
const LockScreen = ({tamil, onUnlocked, onLogout}: Props) => {
  const [message, setMessage] = useState('');

  const tryUnlock = useCallback(async () => {
    setMessage('');
    const ok = await unlock(t(tamil, 'Unlock PayGuard', 'PayGuard-ஐத் திற'));
    if (ok) {
      playSound('unlocked');
      onUnlocked();
    } else {
      setMessage(t(tamil, 'Not unlocked. Try again.', 'திறக்கப்படவில்லை. மீண்டும் முயலுங்கள்.'));
    }
  }, [tamil, onUnlocked]);

  // Ask straight away; the button is there if the person cancels.
  useEffect(() => {
    tryUnlock();
  }, [tryUnlock]);

  return (
    <View style={styles.screen} accessibilityViewIsModal>
      <Text style={styles.icon} importantForAccessibility="no">
        🔒
      </Text>
      <Text style={styles.title} accessibilityRole="header">
        {t(tamil, 'PayGuard is locked', 'PayGuard பூட்டப்பட்டுள்ளது')}
      </Text>
      <Text style={styles.body}>
        {t(tamil, 'Use your fingerprint, face or phone PIN to continue.',
          'தொடர கைரேகை, முகம் அல்லது PIN பயன்படுத்துங்கள்.')}
      </Text>
      <TouchableOpacity onPress={tryUnlock} accessibilityRole="button" style={styles.button}>
        <Text style={styles.buttonText}>{t(tamil, 'Unlock', 'திற')}</Text>
      </TouchableOpacity>
      <TouchableOpacity onPress={onLogout} accessibilityRole="button" style={styles.link}>
        <Text style={styles.linkText}>{t(tamil, 'Log out instead', 'பதிலாக வெளியேறு')}</Text>
      </TouchableOpacity>
      {message ? (
        <Text style={styles.message} accessibilityLiveRegion="polite">
          {message}
        </Text>
      ) : null}
    </View>
  );
};

const styles = StyleSheet.create({
  screen: {
    position: 'absolute',
    top: 0,
    right: 0,
    bottom: 0,
    left: 0,
    backgroundColor: colors.navy,
    alignItems: 'center',
    justifyContent: 'center',
    padding: 32,
    zIndex: 10,
  },
  icon: {
    fontSize: 56,
    marginBottom: 12,
  },
  title: {
    color: '#FFFFFF',
    fontSize: 26,
    fontWeight: '800',
    marginBottom: 10,
  },
  body: {
    color: '#C7D2E3',
    fontSize: 17,
    textAlign: 'center',
    lineHeight: 25,
    marginBottom: 28,
  },
  button: {
    backgroundColor: colors.paypalYellow,
    paddingVertical: 16,
    paddingHorizontal: 48,
    borderRadius: 14,
  },
  buttonText: {
    color: colors.paypalNavy,
    fontSize: 18,
    fontWeight: '800',
  },
  link: {
    marginTop: 18,
    padding: 10,
  },
  linkText: {
    color: '#C7D2E3',
    fontSize: 16,
    textDecorationLine: 'underline',
  },
  message: {
    color: '#FCA5A5',
    fontSize: 16,
    marginTop: 16,
  },
});

export default LockScreen;
