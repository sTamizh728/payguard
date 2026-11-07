import React, {useCallback, useEffect, useState} from 'react';
import {StyleSheet, Text, TouchableOpacity, View} from 'react-native';

import {api} from '../api';
import {TabName} from '../components/TabBar';
import {Session, t} from '../session';
import {colors, TOUCH, ui} from '../theme';

type Alert = {kind: 'bad' | 'warn' | 'good'; text: string};

const greeting = (tamil: boolean) => {
  const hour = new Date().getHours();
  if (tamil) {
    return 'வணக்கம்';
  }
  return hour < 12 ? 'Good morning' : hour < 17 ? 'Good afternoon' : 'Good evening';
};

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
            text: t(tamil, `${failed.length} payment(s) need attention. Open Track.`,
              `${failed.length} கட்டணம்(கள்) கவனிக்க வேண்டும். கண்காணி பாருங்கள்.`),
          });
        }
        if (history.requests.length) {
          found.push({
            kind: 'warn',
            text: t(tamil, `${history.requests.length} customer refund request(s) are waiting for you.`,
              `${history.requests.length} வாடிக்கையாளர் பணத்திருப்பக் கோரிக்கை(கள்) காத்திருக்கின்றன.`),
          });
        }
      } else {
        const waiting = (history.purchases ?? []).filter((p: any) => p.request_status === 'OPEN');
        if (waiting.length) {
          found.push({
            kind: 'warn',
            text: t(tamil, `${waiting.length} refund request(s) are waiting for the shop.`,
              `${waiting.length} பணத்திருப்பக் கோரிக்கை(கள்) கடையின் பதிலுக்குக் காத்திருக்கின்றன.`),
          });
        }
      }
      setAlerts(found);
    } catch (error) {
      session.handleError(error);
    }
  }, [account, tamil, session]);

  useEffect(() => {
    loadAlerts();
  }, [loadAlerts]);

  if (!account) {
    return <>{loginCard}</>;
  }

  const firstName = (account.fullName || account.email).split(/[\s@]/)[0];
  const live = session.liveAlerts.slice(0, 3);
  const nothing = !live.length && !alerts.length;

  const ACTIONS: {tab: TabName; en: string; ta: string; hintEn: string; hintTa: string}[] = [
    {tab: 'assistant', en: 'Talk to PayGuard', ta: 'PayGuard-உடன் பேசு',
      hintEn: 'Shop, pay or ask about payments by voice', hintTa: 'குரலில் வாங்க, செலுத்த, கேட்க'},
    {tab: 'shop', en: 'Shop', ta: 'கடை', hintEn: 'Best-rated products and your cart', hintTa: 'சிறந்த பொருட்கள், கூடை'},
    {tab: 'send', en: 'Send money', ta: 'பணம் அனுப்பு', hintEn: 'To a contact or any PayPal email',
      hintTa: 'தொடர்பு அல்லது PayPal மின்னஞ்சலுக்கு'},
    {tab: 'history', en: 'Track', ta: 'கண்காணி', hintEn: 'Payments, autopay, orders, deliveries',
      hintTa: 'கட்டணங்கள், தானியங்கி, ஆர்டர்கள், டெலிவரி'},
  ];

  return (
    <View>
      <Text style={styles.hello} accessibilityRole="header">
        {greeting(tamil)}, {firstName}
      </Text>

      <View style={ui.card} accessibilityLiveRegion="polite">
        <Text style={ui.heading} accessibilityRole="header">
          {t(tamil, 'Needs your attention', 'கவனிக்க வேண்டியவை')}
        </Text>
        {live.map(alert => (
          <View
            key={`live-${alert.id}`}
            accessible
            style={[styles.alert, ['payment_failed', 'dispute'].includes(alert.kind) ? styles.bad : styles.info]}>
            <Text style={styles.alertText}>{alert.text}</Text>
          </View>
        ))}
        {alerts.map((alert, index) => (
          <View key={index} accessible style={[styles.alert, styles[alert.kind]]}>
            <Text style={styles.alertText}>{alert.text}</Text>
          </View>
        ))}
        {nothing && (
          <Text style={ui.muted}>{t(tamil, 'Nothing right now. You are all set.', 'இப்போது எதுவும் இல்லை.')}</Text>
        )}
        <TouchableOpacity onPress={loadAlerts} accessibilityRole="button" style={styles.textButton}>
          <Text style={styles.textButtonText}>{t(tamil, 'Check again', 'மீண்டும் சரிபார்')}</Text>
        </TouchableOpacity>
      </View>

      <Text style={ui.section} accessibilityRole="header">
        {t(tamil, 'What would you like to do?', 'என்ன செய்ய வேண்டும்?')}
      </Text>
      <View style={[ui.card, styles.list]}>
        {ACTIONS.map((action, index) => (
          <TouchableOpacity
            key={action.tab}
            onPress={() => session.goTo(action.tab)}
            accessibilityRole="button"
            accessibilityLabel={t(tamil, action.en, action.ta)}
            accessibilityHint={t(tamil, action.hintEn, action.hintTa)}
            style={[styles.row, index > 0 && styles.rowLine]}>
            <View style={styles.rowText}>
              <Text style={styles.rowTitle}>{t(tamil, action.en, action.ta)}</Text>
              <Text style={ui.muted}>{t(tamil, action.hintEn, action.hintTa)}</Text>
            </View>
            <Text style={styles.chevron} importantForAccessibility="no">
              ›
            </Text>
          </TouchableOpacity>
        ))}
      </View>

      <Text style={ui.section} accessibilityRole="header">
        {t(tamil, 'How your money stays safe', 'உங்கள் பணம் எப்படி பாதுகாக்கப்படுகிறது')}
      </Text>
      <View style={ui.card}>
        {[
          t(tamil, 'Money moves only after your PayGuard PIN and fingerprint, or in PayPal itself.',
            'உங்கள் PIN, கைரேகை அல்லது PayPal-இல் மட்டுமே பணம் நகரும்.'),
          t(tamil, 'The AI only understands you. It can never send money by itself.',
            'AI உங்களைப் புரிந்துகொள்ள மட்டுமே. அது தானாகப் பணம் அனுப்ப முடியாது.'),
          t(tamil, 'Scam check, limits, and tricks like "skip the confirmation" are blocked.',
            'மோசடி சோதனை, வரம்புகள்; "உறுதிப்படுத்தலைத் தவிர்" போன்ற தந்திரங்கள் தடுக்கப்படும்.'),
        ].map(line => (
          <View key={line} style={styles.point}>
            <View style={styles.dot} />
            <Text style={[ui.body, styles.pointText]}>{line}</Text>
          </View>
        ))}
      </View>
    </View>
  );
};

const styles = StyleSheet.create({
  hello: {
    color: colors.ink,
    fontSize: 26,
    fontWeight: '700',
    letterSpacing: -0.4,
    marginBottom: 14,
    marginTop: 4,
  },
  alert: {
    borderRadius: 10,
    paddingVertical: 10,
    paddingHorizontal: 12,
    marginBottom: 8,
    borderLeftWidth: 4,
  },
  alertText: {
    color: colors.ink,
    fontSize: 16,
    lineHeight: 23,
  },
  bad: {backgroundColor: colors.badBg, borderLeftColor: colors.bad},
  warn: {backgroundColor: colors.warnBg, borderLeftColor: colors.warn},
  good: {backgroundColor: colors.goodBg, borderLeftColor: colors.good},
  info: {backgroundColor: colors.brandSoft, borderLeftColor: colors.brand},
  textButton: {
    minHeight: TOUCH,
    justifyContent: 'center',
    alignSelf: 'flex-start',
    marginTop: 2,
  },
  textButtonText: {
    color: colors.brandBlue,
    fontSize: 16,
    fontWeight: '600',
    textDecorationLine: 'underline',
  },
  list: {
    paddingVertical: 4,
  },
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    minHeight: 64,
    paddingVertical: 10,
  },
  rowLine: {
    borderTopWidth: 1,
    borderTopColor: colors.line,
  },
  rowText: {
    flex: 1,
  },
  rowTitle: {
    color: colors.ink,
    fontSize: 17,
    fontWeight: '700',
    marginBottom: 2,
  },
  chevron: {
    color: colors.muted,
    fontSize: 28,
    marginLeft: 8,
  },
  point: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    marginBottom: 8,
  },
  dot: {
    width: 7,
    height: 7,
    borderRadius: 4,
    backgroundColor: colors.brand,
    marginTop: 9,
    marginRight: 10,
  },
  pointText: {
    flex: 1,
  },
});

export default HomeScreen;
