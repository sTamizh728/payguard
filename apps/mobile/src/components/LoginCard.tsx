import React, {useState} from 'react';
import {StyleSheet, Text, TextInput, TouchableOpacity, View} from 'react-native';

import {colors, ui} from '../theme';

type Props = {
  busy: boolean;
  message: string;
  onPayPal: () => void;
  onEmail: (form: {
    email: string;
    password: string;
    fullName: string;
    register: boolean;
  }) => void;
};

const LoginCard = ({busy, message, onPayPal, onEmail}: Props) => {
  const [showEmail, setShowEmail] = useState(false);
  const [register, setRegister] = useState(false);
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [fullName, setFullName] = useState('');

  return (
    <View style={ui.card}>
      <Text style={ui.heading} accessibilityRole="header">
        Log in
      </Text>
      <TouchableOpacity
        onPress={onPayPal}
        disabled={busy}
        accessibilityRole="button"
        accessibilityLabel="Log in with PayPal"
        accessibilityState={{disabled: busy, busy}}
        style={styles.paypalButton}>
        <Text style={styles.paypalText}>Log in with PayPal</Text>
      </TouchableOpacity>

      <TouchableOpacity
        onPress={() => setShowEmail(!showEmail)}
        accessibilityRole="button"
        accessibilityState={{expanded: showEmail}}
        style={ui.secondaryButton}>
        <Text style={ui.secondaryButtonText}>Use email instead</Text>
      </TouchableOpacity>

      {showEmail && (
        <View style={styles.form}>
          {register && (
            <>
              <Text style={ui.label} nativeID="fullNameLabel">
                Full name
              </Text>
              <TextInput
                value={fullName}
                onChangeText={setFullName}
                accessibilityLabelledBy="fullNameLabel"
                autoComplete="name"
                style={ui.input}
              />
            </>
          )}
          <Text style={ui.label} nativeID="emailLabel">
            Email
          </Text>
          <TextInput
            value={email}
            onChangeText={setEmail}
            accessibilityLabelledBy="emailLabel"
            autoCapitalize="none"
            autoComplete="email"
            keyboardType="email-address"
            style={ui.input}
          />
          <Text style={ui.label} nativeID="passwordLabel">
            Password
          </Text>
          <TextInput
            value={password}
            onChangeText={setPassword}
            accessibilityLabelledBy="passwordLabel"
            accessibilityHint="At least 8 characters"
            autoCapitalize="none"
            autoComplete={register ? 'new-password' : 'current-password'}
            secureTextEntry
            style={ui.input}
          />
          <TouchableOpacity
            onPress={() => onEmail({email, password, fullName, register})}
            disabled={busy}
            accessibilityRole="button"
            accessibilityState={{disabled: busy, busy}}
            style={ui.primaryButton}>
            <Text style={ui.primaryButtonText}>
              {register ? 'Create account' : 'Log in'}
            </Text>
          </TouchableOpacity>
          <TouchableOpacity
            onPress={() => setRegister(!register)}
            accessibilityRole="button">
            <Text style={styles.link}>
              {register ? 'I already have an account' : 'Create a new account'}
            </Text>
          </TouchableOpacity>
          <Text style={[ui.muted, styles.note]}>
            Email accounts can chat with PayGuard. Log in with PayPal to see your
            purchases, send money or ask for refunds.
          </Text>
        </View>
      )}

      {message ? (
        <Text style={ui.error} accessibilityLiveRegion="polite">
          {message}
        </Text>
      ) : null}
    </View>
  );
};

const styles = StyleSheet.create({
  paypalButton: {
    backgroundColor: colors.paypalYellow,
    paddingVertical: 16,
    borderRadius: 12,
    alignItems: 'center',
  },
  paypalText: {
    color: colors.paypalNavy,
    fontSize: 17,
    fontWeight: '800',
  },
  form: {
    marginTop: 8,
  },
  link: {
    color: colors.brandBlue,
    fontSize: 15,
    textAlign: 'center',
    marginTop: 14,
    textDecorationLine: 'underline',
  },
  note: {
    marginTop: 12,
  },
});

export default LoginCard;
