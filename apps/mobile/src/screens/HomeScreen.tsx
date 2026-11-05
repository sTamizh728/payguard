import React, {useCallback, useEffect, useState} from 'react';
import {StyleSheet, Text, TouchableOpacity, View} from 'react-native';

import {api} from '../api';
import {Session, t} from '../session';
import {colors, ui} from '../theme';

type Alert = {kind: 'bad' | 'warn' | 'good'; text: string};

const HomeScreen = ({session, loginCard}: {session: Session; loginCard: React.ReactNode}) => {
  const {account, tamil} = session;
  const [alerts, setAlerts] = useState<Alert[]>([]);

  const loadAlerts = useCallback(async () => {
    if (!account) {
      setAlerts([]);
      return;
    }
    try {
      const history = await api('/api/history', account.token);
      const found: Alert[] = [];

      if (history.role === 'owner') {
        const failed = history.sent.filter((p: any) =>
          ['FAILED', 'DENIED', 'RETURNED', 'BLOCKED', 'UNCLAIMED', 'UNKNOWN'].includes(p.status),
        );
        if (failed.length) {
          found.push({
            kind: 'bad',
            text: t(
              tamil,
              `${failed.length} payment(s) need attention. Open History.`,
              `${failed.length} கட்டணம்(கள்) கவனிக்க வேண்டும். வரலாறு பாருங்கள்.`,
            ),
          });
        }
        if (history.requests.length) {
          found.push({
            kind: 'warn',
            text: t(
              tamil,
              `${history.requests.length} customer refund request(s) are waiting for you.`,
              `${history.requests.length} வாடிக்கையாளர் பணத்திருப்பக் கோரிக்கை(கள்) காத்திருக்கின்றன.`,
            ),
          });
        }
      } else {
        const waiting = history.purchases.filter((p: any) => p.request_status === 'OPEN');
        if (waiting.length) {
          found.push({
            kind: 'warn',
            text: t(
              tamil,
              `${waiting.length} refund request(s) are waiting for the shop.`,
              `${waiting.length} பணத்திருப்பக் கோரிக்கை(கள்) கடையின் பதிலுக்குக் காத்திருக்கின்றன.`,
            ),
          });
        }
      }

      if (!found.length) {
        found.push({
          kind: 'good',
          text: t(tamil, 'All good. Nothing needs your attention.', 'எல்லாம் சரி. கவனிக்க எதுவும் இல்லை.'),
        });
      }
      setAlerts(found);
    } catch (error) {
      session.handleError(error);
    }
  }, [account, tamil, session]);

  useEffect(() => {
    loadAlerts();
  }, [loadAlerts]);

  return (
    <View>
      {account ? (
        <View style={ui.card}>
          <Text style={ui.title} accessibilityRole="header">
            {t(tamil, 'Hello', 'வணக்கம்')}, {account.fullName || account.email}
          </Text>
          <Text style={ui.muted}>
            {account.isOwner
              ? t(tamil, 'You are the account owner.', 'நீங்கள் கணக்கு உரிமையாளர்.')
              : t(tamil, 'You are logged in as a customer.', 'நீங்கள் வாடிக்கையாளராக உள்நுழைந்துள்ளீர்கள்.')}
          </Text>
        </View>
      ) : (
        loginCard
      )}

      {account && (
        <View style={ui.card} accessibilityLiveRegion="polite">
          <Text style={ui.heading} accessibilityRole="header">
            {t(tamil, 'Alerts', 'எச்சரிக்கைகள்')}
          </Text>
          {session.liveAlerts.slice(0, 3).map(alert => (
            <Text
              key={`live-${alert.id}`}
              style={[
                styles.alert,
                ['payment_failed', 'dispute'].includes(alert.kind) ? styles.bad : styles.good,
              ]}>
              🔔 {alert.text}
            </Text>
          ))}
          {alerts.map((alert, index) => (
            <Text key={index} style={[styles.alert, styles[alert.kind]]}>
              {alert.text}
            </Text>
          ))}
          <TouchableOpacity onPress={loadAlerts} accessibilityRole="button" style={ui.secondaryButton}>
            <Text style={ui.secondaryButtonText}>{t(tamil, 'Check again', 'மீண்டும் சரிபார்')}</Text>
          </TouchableOpacity>
        </View>
      )}

      {account && (
        <View style={styles.quickRow}>
          <TouchableOpacity
            onPress={() => session.goTo('assistant')}
            accessibilityRole="button"
            style={[styles.quick, {backgroundColor: colors.brandBlue}]}>
            <Text style={styles.quickText}>🎙️ {t(tamil, 'Talk to PayGuard', 'PayGuard-உடன் பேசு')}</Text>
          </TouchableOpacity>
          {account.isOwner && (
            <TouchableOpacity
              onPress={() => session.goTo('send')}
              accessibilityRole="button"
              style={[styles.quick, {backgroundColor: colors.good}]}>
              <Text style={styles.quickText}>💸 {t(tamil, 'Send money', 'பணம் அனுப்பு')}</Text>
            </TouchableOpacity>
          )}
        </View>
      )}

      <View style={ui.card}>
        <Text style={ui.heading} accessibilityRole="header">
          {t(tamil, 'What is PayGuard?', 'PayGuard என்றால் என்ன?')}
        </Text>
        <Text style={ui.body}>
          {t(
            tamil,
            'PayGuard is a voice and chat assistant for PayPal. Talk or type in English or Tamil to send money, check your payment history, find failed or returned payments, and handle refunds.',
            'PayGuard என்பது PayPal-க்கான குரல் மற்றும் அரட்டை உதவியாளர். தமிழிலோ ஆங்கிலத்திலோ பேசி அல்லது தட்டச்சு செய்து பணம் அனுப்பலாம், கட்டண வரலாறு பார்க்கலாம், தோல்வியடைந்த கட்டணங்களைக் கண்டறியலாம், பணத்திருப்பம் செய்யலாம்.',
          )}
        </Text>
        <Text style={[ui.heading, styles.gap]}>{t(tamil, 'How it keeps you safe', 'உங்களை எப்படி பாதுகாக்கிறது')}</Text>
        {[
          t(tamil, 'Money moves only after your fingerprint, face or phone PIN.', 'உங்கள் கைரேகை, முகம் அல்லது PIN இல்லாமல் பணம் நகராது.'),
          t(tamil, 'The AI only understands you. It can never send money by itself.', 'AI உங்களைப் புரிந்துகொள்ள மட்டுமே. அது தானாகப் பணம் அனுப்ப முடியாது.'),
          t(tamil, 'Limits: $100 per payment and $200 a day.', 'வரம்பு: ஒரு கட்டணத்துக்கு $100, ஒரு நாளுக்கு $200.'),
          t(tamil, 'Tricks like "skip the confirmation" are blocked.', '"உறுதிப்படுத்தலைத் தவிர்" போன்ற தந்திரங்கள் தடுக்கப்படும்.'),
        ].map(line => (
          <Text key={line} style={[ui.body, styles.bullet]}>
            • {line}
          </Text>
        ))}
      </View>
    </View>
  );
};

const styles = StyleSheet.create({
  alert: {
    fontSize: 16,
    lineHeight: 23,
    padding: 12,
    borderRadius: 10,
    marginBottom: 8,
  },
  bad: {backgroundColor: colors.badBg, color: colors.bad},
  warn: {backgroundColor: colors.warnBg, color: colors.warn},
  good: {backgroundColor: colors.goodBg, color: colors.good},
  quickRow: {
    flexDirection: 'row',
    gap: 10,
    marginBottom: 16,
  },
  quick: {
    flex: 1,
    paddingVertical: 18,
    borderRadius: 14,
    alignItems: 'center',
  },
  quickText: {
    color: '#FFFFFF',
    fontSize: 16,
    fontWeight: '800',
  },
  gap: {
    marginTop: 16,
  },
  bullet: {
    marginTop: 4,
  },
});

export default HomeScreen;
