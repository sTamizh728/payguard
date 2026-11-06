import React, {useCallback, useEffect, useMemo, useRef, useState} from 'react';
import {
  AccessibilityInfo,
  AppState,
  Linking,
  Platform,
  SafeAreaView,
  ScrollView,
  StatusBar,
  StyleSheet,
  Text,
  View,
} from 'react-native';

import {api, LoginExpired} from './src/api';
import LockScreen from './src/components/LockScreen';
import LoginCard from './src/components/LoginCard';
import TabBar, {TabName} from './src/components/TabBar';
import AssistantScreen from './src/screens/AssistantScreen';
import HistoryScreen from './src/screens/HistoryScreen';
import HomeScreen from './src/screens/HomeScreen';
import ProfileScreen from './src/screens/ProfileScreen';
import SendScreen from './src/screens/SendScreen';
import ShopScreen from './src/screens/ShopScreen';
import {playSound} from './src/native';
import {Account, LiveAlert, Session, setUpPhoneSecurity} from './src/session';
import {colors} from './src/theme';

const APP_AUTH_PREFIX = 'accessiblecommerce://auth';
const APP_SHOP_PREFIX = 'accessiblecommerce://shop';

const ALERT_SOUNDS: Record<string, string> = {
  payment_received: 'money_received',
  refund_done: 'money_received',
  payment_sent: 'payment_sent',
  order_paid: 'payment_sent',
  payment_failed: 'warning',
  dispute: 'warning',
  autopay: 'request_sent',
};

const LOGIN_ERRORS: Record<string, string> = {
  cancelled: 'PayPal login was cancelled.',
  expired: 'The login took too long. Please try again.',
  missing_state: 'The login link was incomplete. Please try again.',
  no_email: 'PayPal did not share your email address.',
  paypal_unavailable: 'PayPal is not reachable right now. Please try again.',
  account_conflict:
    'An account with this email already exists. Log in with your email and password instead.',
};

// Random secret that ties a PayPal login to this phone.
const makeNonce = () => {
  const chars =
    'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_';
  const bytes = new Uint8Array(48);
  const cryptoApi = (globalThis as any).crypto;

  if (cryptoApi?.getRandomValues) {
    cryptoApi.getRandomValues(bytes);
  } else {
    for (let i = 0; i < bytes.length; i++) {
      bytes[i] = Math.floor(Math.random() * 256);
    }
  }

  return Array.from(bytes, b => chars[b % chars.length]).join('');
};

const readQuery = (url: string) => {
  const result: Record<string, string> = {};
  const query = url.split('?')[1] ?? '';

  for (const pair of query.split('&')) {
    const [key, value = ''] = pair.split('=');
    if (key) {
      result[decodeURIComponent(key)] = decodeURIComponent(
        value.replace(/\+/g, ' '),
      );
    }
  }

  return result;
};

const App = () => {
  const [account, setAccount] = useState<Account | null>(null);
  const [tamil, setTamil] = useState(false);
  const [tab, setTab] = useState<TabName>('home');
  const [authBusy, setAuthBusy] = useState(false);
  const [authMessage, setAuthMessage] = useState('');
  const pendingNonce = useRef<string | null>(null);
  const [locked, setLocked] = useState(false);
  const leftAt = useRef<number | null>(null);
  const [liveAlerts, setLiveAlerts] = useState<LiveAlert[]>([]);
  const lastAlertId = useRef(0);

  const logout = useCallback((message = '') => {
    setAccount(null);
    setLocked(false);
    setAuthMessage(message);
    setTab('home');
  }, []);

  // App lock: away for more than 15 seconds -> fingerprint / face / PIN again.
  // (Short trips, like a permission pop-up, don't lock.)
  useEffect(() => {
    const subscription = AppState.addEventListener('change', state => {
      if (state === 'background') {
        leftAt.current = Date.now();
      } else if (state === 'active' && leftAt.current !== null) {
        const away = Date.now() - leftAt.current;
        leftAt.current = null;
        if (account && away > 15000) {
          setLocked(true);
        }
      }
    });
    return () => subscription.remove();
  }, [account]);

  const handleError = useCallback(
    (error: unknown) => {
      if (error instanceof LoginExpired) {
        logout(error.message);
        return error.message;
      }
      return error instanceof Error ? error.message : 'Something went wrong.';
    },
    [logout],
  );

  const session: Session = useMemo(
    () => ({account, liveAlerts, tamil, setTamil, logout, goTo: setTab, handleError}),
    [account, liveAlerts, tamil, logout, handleError],
  );

  // Real-time alerts from PayPal webhooks: check every 20 seconds while open.
  useEffect(() => {
    if (!account) {
      setLiveAlerts([]);
      lastAlertId.current = 0;
      return;
    }
    let first = true;
    const check = async () => {
      if (AppState.currentState !== 'active') {
        return;
      }
      try {
        const data = await api<{notifications: LiveAlert[]}>(
          `/api/notifications?after_id=${lastAlertId.current}`,
          account.token,
        );
        const fresh = data.notifications;
        if (!fresh.length) {
          return;
        }
        lastAlertId.current = Math.max(...fresh.map(n => n.id));
        setLiveAlerts(current => [...fresh, ...current].slice(0, 20));
        // Old alerts load quietly on login; new ones are announced.
        if (!first) {
          playSound(ALERT_SOUNDS[fresh[0].kind] ?? 'request_sent');
          AccessibilityInfo.announceForAccessibility(fresh[0].text);
        }
      } catch {
        // Offline for a moment: try again next time.
      } finally {
        first = false;
      }
    };
    check();
    const timer = setInterval(check, 20000);
    return () => clearInterval(timer);
  }, [account]);

  const finishLogin = async (token: string) => {
    const data = await api('/api/auth/me', token);
    setAccount({
      token,
      email: data.email,
      fullName: data.full_name,
      isOwner: Boolean(data.is_owner),
    });
    setAuthMessage('');

    // Register this phone's fingerprint/PIN key now, while the login is fresh.
    try {
      const problem = await setUpPhoneSecurity(token);
      if (problem) {
        setAuthMessage(problem);
      }
    } catch (error) {
      setAuthMessage(error instanceof Error ? error.message : 'Security setup failed.');
    }
  };

  // The newest account, for links that arrive while the app is running.
  const accountRef = useRef<Account | null>(null);
  accountRef.current = account;

  // PayPal sends people straight back into the app, so the phone browser
  // never has to open our server:
  //   accessiblecommerce://auth/paypal?code=..&state=..   (Log in with PayPal)
  //   accessiblecommerce://shop/paid?token=ORDER_ID       (checkout approved)
  //   accessiblecommerce://shop/cancel                    (checkout cancelled)
  const handleAppLink = useCallback(async (url?: string | null) => {
    if (!url) {
      return;
    }
    const params = readQuery(url);

    if (url.startsWith(APP_SHOP_PREFIX)) {
      const current = accountRef.current;
      setTab('shop');
      if (url.startsWith(`${APP_SHOP_PREFIX}/cancel`)) {
        setAuthMessage('Payment cancelled. No money was taken.');
        return;
      }
      if (!current || !params.token) {
        setAuthMessage('Please log in, then open the order in Shop to pay.');
        return;
      }
      setAuthMessage('Finishing your PayPal payment...');
      try {
        await api('/api/shop/complete', current.token, {body: {order_id: params.token}});
        setAuthMessage('Payment complete. Thank you!');
        playSound('payment_sent');
      } catch (error) {
        setAuthMessage(error instanceof Error ? error.message : 'The payment could not be finished.');
        playSound('failed');
      }
      return;
    }

    if (!url.startsWith(APP_AUTH_PREFIX)) {
      return;
    }

    const nonce = pendingNonce.current;
    pendingNonce.current = null;

    if (params.error) {
      setAuthMessage(LOGIN_ERRORS[params.error] ?? 'PayPal login was cancelled.');
      return;
    }

    if (!params.code || !nonce) {
      setAuthMessage('PayPal login could not be completed. Please try again.');
      return;
    }

    setAuthBusy(true);
    try {
      // New flow: PayPal's own code + state. Old flow: our one-time code.
      const data = params.state
        ? await api('/api/auth/paypal/finish', null, {
            body: {code: params.code, state: params.state, app_nonce: nonce},
          })
        : await api('/api/auth/paypal/exchange', null, {
            body: {code: params.code, app_nonce: nonce},
          });
      await finishLogin(data.access_token);
    } catch (error) {
      setAuthMessage(error instanceof Error ? error.message : 'PayPal login failed.');
    } finally {
      setAuthBusy(false);
    }
  }, []);

  useEffect(() => {
    const subscription = Linking.addEventListener('url', event =>
      handleAppLink(event.url),
    );
    Linking.getInitialURL().then(handleAppLink);
    return () => subscription.remove();
  }, [handleAppLink]);

  const startPayPalLogin = async () => {
    const nonce = makeNonce();
    pendingNonce.current = nonce;
    setAuthMessage('Opening PayPal...');

    try {
      // Ask our server for PayPal's address, then open paypal.com directly.
      const {url} = await api(`/api/auth/paypal/login-url?app_nonce=${nonce}`, null);
      await Linking.openURL(url);
    } catch {
      pendingNonce.current = null;
      setAuthMessage('Could not open PayPal login. Please try again.');
    }
  };

  const emailLogin = async (form: {
    email: string;
    password: string;
    fullName: string;
    register: boolean;
  }) => {
    if (!form.email.trim() || form.password.length < 8) {
      setAuthMessage('Enter your email and a password of at least 8 characters.');
      return;
    }
    if (form.register && form.fullName.trim().length < 2) {
      setAuthMessage('Enter your full name.');
      return;
    }

    setAuthBusy(true);
    setAuthMessage('');
    try {
      if (form.register) {
        await api('/api/auth/register', null, {
          body: {
            email: form.email.trim(),
            password: form.password,
            full_name: form.fullName.trim(),
          },
        });
      }
      const data = await api('/api/auth/login', null, {
        body: {email: form.email.trim(), password: form.password},
      });
      await finishLogin(data.access_token);
    } catch (error) {
      setAuthMessage(error instanceof Error ? error.message : 'Login failed.');
    } finally {
      setAuthBusy(false);
    }
  };

  const loginCard = (
    <LoginCard
      busy={authBusy}
      message={authMessage}
      onPayPal={startPayPalLogin}
      onEmail={emailLogin}
    />
  );

  const screen = () => {
    switch (tab) {
      case 'assistant':
        return <AssistantScreen session={session} />;
      case 'send':
        return <SendScreen session={session} />;
      case 'shop':
        return <ShopScreen session={session} />;
      case 'history':
        return <HistoryScreen session={session} />;
      case 'profile':
        return <ProfileScreen session={session} />;
      default:
        return <HomeScreen session={session} loginCard={loginCard} />;
    }
  };

  return (
    <SafeAreaView style={styles.container}>
      <StatusBar barStyle="light-content" />

      <View style={styles.header}>
        <View>
          <Text style={styles.logo}>PAYPAL AI ASSISTANT</Text>
          <Text style={styles.brand} accessibilityRole="header">
            PayGuard
          </Text>
        </View>
        {account && (
          <Text style={styles.role}>{account.isOwner ? '🔑 Owner' : '👤 Customer'}</Text>
        )}
      </View>

      {account && authMessage ? (
        <Text style={styles.banner} accessibilityLiveRegion="polite">
          {authMessage}
        </Text>
      ) : null}

      <View style={styles.body}>
        {tab === 'assistant' ? (
          screen()
        ) : (
          <ScrollView contentContainerStyle={styles.scroll} keyboardShouldPersistTaps="handled">
            {screen()}
          </ScrollView>
        )}
      </View>

      <TabBar current={tab} onChange={setTab} tamil={tamil} />

      {locked && account && (
        <LockScreen
          tamil={tamil}
          onUnlocked={() => setLocked(false)}
          onLogout={() => logout()}
        />
      )}
    </SafeAreaView>
  );
};

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: colors.navy,
  },
  header: {
    backgroundColor: colors.navy,
    paddingHorizontal: 20,
    paddingBottom: 14,
    // The app draws edge-to-edge: keep the header below the phone's status bar.
    paddingTop: 14 + (Platform.OS === 'android' ? StatusBar.currentHeight ?? 24 : 0),
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
  },
  logo: {
    color: '#8BB9FF',
    fontSize: 11,
    fontWeight: '800',
    letterSpacing: 2,
  },
  brand: {
    color: '#FFFFFF',
    fontSize: 22,
    fontWeight: '800',
    marginTop: 2,
  },
  role: {
    color: '#FFFFFF',
    fontSize: 14,
    fontWeight: '700',
    backgroundColor: '#263449',
    paddingHorizontal: 12,
    paddingVertical: 6,
    borderRadius: 16,
  },
  banner: {
    backgroundColor: colors.warnBg,
    color: colors.warn,
    padding: 10,
    fontSize: 14,
  },
  body: {
    flex: 1,
    backgroundColor: colors.page,
  },
  scroll: {
    padding: 16,
  },
});

export default App;
