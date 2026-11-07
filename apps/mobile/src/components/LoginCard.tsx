import React, {useState} from 'react';
import {Linking, StyleSheet, Text, TextInput, TouchableOpacity, View} from 'react-native';

import {colors, TOUCH, ui} from '../theme';
import BrandMark from './BrandMark';

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

const SANDBOX_ACCOUNTS = 'https://developer.paypal.com/dashboard/accounts';

/** The first screen: what PayGuard is, Log in with PayPal, and help for testers. */
const LoginCard = ({busy, message, onPayPal, onEmail}: Props) => {
  const [showEmail, setShowEmail] = useState(false);
  const [showHelp, setShowHelp] = useState(false);
  const [register, setRegister] = useState(false);
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [fullName, setFullName] = useState('');

  return (
    <View>
      <View style={styles.hero}>
        <BrandMark size={52} />
        <Text style={styles.heroTitle} accessibilityRole="header">
          Talk to PayPal, safely.
        </Text>
        <Text style={styles.heroText}>
          Shop, pay friends, set up autopay and track every payment by voice or by tapping, in
          English or Tamil. Nothing is paid without your PIN and fingerprint.
        </Text>
      </View>

      <View style={ui.card}>
        <TouchableOpacity
          onPress={onPayPal}
          disabled={busy}
          accessibilityRole="button"
          accessibilityLabel="Log in with PayPal"
          accessibilityHint="Opens PayPal to log in, then comes back here"
          accessibilityState={{disabled: busy, busy}}
          style={[styles.paypalButton, busy && ui.disabled]}>
          <Text style={styles.paypalText}>{busy ? 'Opening PayPal…' : 'Log in with PayPal'}</Text>
        </TouchableOpacity>
        <Text style={[ui.muted, styles.center]}>This demo uses PayPal sandbox (test money).</Text>

        {message ? (
          <Text style={ui.error} accessibilityLiveRegion="polite">
            {message}
          </Text>
        ) : null}

        <TouchableOpacity
          onPress={() => setShowHelp(!showHelp)}
          accessibilityRole="button"
          accessibilityState={{expanded: showHelp}}
          style={styles.linkButton}>
          <Text style={styles.link}>No PayPal test account?</Text>
        </TouchableOpacity>
        {showHelp && (
          <View style={styles.help}>
            <Text style={ui.body}>
              PayGuard runs on PayPal's sandbox, so you log in with a sandbox (test) account, not a
              real one.
            </Text>
            <Text style={[ui.body, styles.step]}>
              Judges: ready-made test accounts and their passwords are in the Devpost testing
              instructions.
            </Text>
            <Text style={[ui.body, styles.step]}>
              Your own: open the PayPal developer dashboard, log in with any PayPal account, then
              Sandbox, Accounts, Create account (Personal). Use that email and password here.
            </Text>
            <TouchableOpacity
              onPress={() => Linking.openURL(SANDBOX_ACCOUNTS)}
              accessibilityRole="link"
              style={ui.secondaryButton}>
              <Text style={ui.secondaryButtonText}>Open the PayPal developer dashboard</Text>
            </TouchableOpacity>
            <Text style={[ui.muted, styles.step]}>
              After you log in, PayGuard asks you to choose a PIN. Your fingerprint or phone lock is
              used together with it.
            </Text>
          </View>
        )}

        <TouchableOpacity
          onPress={() => setShowEmail(!showEmail)}
          accessibilityRole="button"
          accessibilityState={{expanded: showEmail}}
          style={styles.linkButton}>
          <Text style={styles.link}>Use email instead</Text>
        </TouchableOpacity>

        {showEmail && (
          <View>
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
              <Text style={ui.primaryButtonText}>{register ? 'Create account' : 'Log in'}</Text>
            </TouchableOpacity>
            <TouchableOpacity onPress={() => setRegister(!register)} accessibilityRole="button" style={styles.linkButton}>
              <Text style={styles.link}>{register ? 'I already have an account' : 'Create a new account'}</Text>
            </TouchableOpacity>
            <Text style={ui.muted}>
              With email you can shop, pay with PayPal, set up autopay and talk to PayGuard. Log in
              with PayPal to see past purchases and ask for refunds.
            </Text>
          </View>
        )}
      </View>
    </View>
  );
};

const styles = StyleSheet.create({
  hero: {
    alignItems: 'flex-start',
    paddingTop: 8,
    paddingBottom: 18,
  },
  heroTitle: {
    color: colors.ink,
    fontSize: 28,
    fontWeight: '700',
    letterSpacing: -0.5,
    marginTop: 16,
    marginBottom: 8,
  },
  heroText: {
    color: colors.muted,
    fontSize: 17,
    lineHeight: 25,
  },
  paypalButton: {
    backgroundColor: colors.paypalYellow,
    minHeight: 54,
    borderRadius: 27,
    alignItems: 'center',
    justifyContent: 'center',
  },
  paypalText: {
    color: colors.paypalNavy,
    fontSize: 18,
    fontWeight: '800',
  },
  center: {
    textAlign: 'center',
    marginTop: 8,
  },
  linkButton: {
    minHeight: TOUCH,
    justifyContent: 'center',
    alignItems: 'center',
    marginTop: 6,
  },
  link: {
    color: colors.brandBlue,
    fontSize: 16,
    fontWeight: '600',
    textDecorationLine: 'underline',
  },
  help: {
    backgroundColor: colors.sunk,
    borderRadius: 12,
    padding: 14,
    marginTop: 4,
    marginBottom: 6,
  },
  step: {
    marginTop: 10,
  },
});

export default LoginCard;
