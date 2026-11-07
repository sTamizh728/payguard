import React, {useEffect, useState} from 'react';
import {StyleSheet, Text, TouchableOpacity, View} from 'react-native';

import {api} from '../api';
import {securityStatus} from '../native';
import PinSetup from '../components/PinSetup';
import {Session, setUpPhoneSecurity, t} from '../session';
import {colors, ui} from '../theme';

const ProfileScreen = ({session}: {session: Session}) => {
  const {account, tamil} = session;
  const [security, setSecurity] = useState('');
  const [changingPin, setChangingPin] = useState(false);
  const [pinMessage, setPinMessage] = useState('');

  useEffect(() => {
    if (!account) {
      return;
    }
    (async () => {
      const local = await securityStatus();
      try {
        const server = await api('/api/security/status', account.token);
        setSecurity(
          !local.available
            ? local.reason
            : server.has_device_key
              ? t(tamil, 'On: payments need your fingerprint, face or PIN.', 'இயக்கத்தில்: கைரேகை, முகம் அல்லது PIN தேவை.')
              : t(tamil, 'Not set up on this phone yet.', 'இந்த போனில் இன்னும் அமைக்கப்படவில்லை.'),
        );
      } catch (error) {
        setSecurity(session.handleError(error));
      }
    })();
  }, [account, tamil, session]);

  return (
    <View>
      {account && (
        <View style={ui.card}>
          <Text style={ui.title} accessibilityRole="header">
            {account.fullName || t(tamil, 'Your profile', 'உங்கள் சுயவிவரம்')}
          </Text>
          <Text style={ui.body}>{account.email}</Text>
          <Text style={[ui.muted, styles.gap]}>
            {account.isOwner
              ? t(tamil, 'Role: account owner (can send money and refund)', 'பங்கு: கணக்கு உரிமையாளர்')
              : t(tamil, 'Role: customer', 'பங்கு: வாடிக்கையாளர்')}
          </Text>
        </View>
      )}

      {account && (
        <View style={ui.card}>
          <Text style={ui.heading} accessibilityRole="header">
            {t(tamil, 'Security', 'பாதுகாப்பு')}
          </Text>
          <Text style={ui.body} accessibilityLiveRegion="polite">
            {security || '…'}
          </Text>
          <TouchableOpacity
            onPress={async () => {
              try {
                const problem = await setUpPhoneSecurity(account.token);
                setSecurity(problem || t(tamil, 'On: payments need your fingerprint, face or PIN.', 'இயக்கத்தில்.'));
              } catch (error) {
                setSecurity(session.handleError(error));
              }
            }}
            accessibilityRole="button"
            style={ui.secondaryButton}>
            <Text style={ui.secondaryButtonText}>{t(tamil, 'Set up security again', 'பாதுகாப்பை மீண்டும் அமை')}</Text>
          </TouchableOpacity>
        </View>
      )}

      {account && changingPin && (
        <PinSetup
          token={account.token}
          tamil={tamil}
          change
          onDone={() => {
            setChangingPin(false);
            setPinMessage(t(tamil, 'Your new PayGuard PIN is saved.', 'புதிய PIN சேமிக்கப்பட்டது.'));
          }}
          onCancel={() => setChangingPin(false)}
        />
      )}

      {account && !changingPin && (
        <View style={ui.card}>
          <Text style={ui.heading} accessibilityRole="header">
            {t(tamil, 'PayGuard PIN', 'PayGuard PIN')}
          </Text>
          <Text style={ui.body} accessibilityLiveRegion="polite">
            {pinMessage ||
              t(tamil, 'Asked before sending money, refunding and showing your balance.',
                'பணம் அனுப்ப, திருப்ப, இருப்பைப் பார்க்க தேவை.')}
          </Text>
          <TouchableOpacity onPress={() => setChangingPin(true)} accessibilityRole="button" style={ui.secondaryButton}>
            <Text style={ui.secondaryButtonText}>{t(tamil, 'Change PIN', 'PIN-ஐ மாற்று')}</Text>
          </TouchableOpacity>
        </View>
      )}

      <View style={ui.card}>
        <Text style={ui.heading} accessibilityRole="header" nativeID="langLabel">
          {t(tamil, 'Language', 'மொழி')}
        </Text>
        <View style={styles.row} accessibilityRole="radiogroup" accessibilityLabelledBy="langLabel">
          {[
            {value: false, label: 'English'},
            {value: true, label: 'தமிழ்'},
          ].map(option => (
            <TouchableOpacity
              key={option.label}
              onPress={() => session.setTamil(option.value)}
              accessibilityRole="radio"
              accessibilityState={{checked: tamil === option.value}}
              style={[styles.lang, tamil === option.value && styles.langSelected]}>
              <Text style={styles.langText}>{option.label}</Text>
            </TouchableOpacity>
          ))}
        </View>
      </View>

      {account && (
        <TouchableOpacity onPress={() => session.logout()} accessibilityRole="button" style={[ui.secondaryButton, styles.logout]}>
          <Text style={[ui.secondaryButtonText, styles.logoutText]}>{t(tamil, 'Log out', 'வெளியேறு')}</Text>
        </TouchableOpacity>
      )}
    </View>
  );
};

const styles = StyleSheet.create({
  gap: {
    marginTop: 8,
  },
  row: {
    flexDirection: 'row',
    gap: 10,
  },
  lang: {
    flex: 1,
    borderWidth: 1,
    borderColor: colors.line,
    borderRadius: 12,
    paddingVertical: 14,
    alignItems: 'center',
  },
  langSelected: {
    borderColor: colors.brandBlue,
    borderWidth: 2,
    backgroundColor: '#E8F0FE',
  },
  langText: {
    color: colors.ink,
    fontSize: 17,
    fontWeight: '700',
  },
  logout: {
    marginBottom: 24,
  },
  logoutText: {
    color: colors.bad,
  },
});

export default ProfileScreen;
