import React, {useCallback, useEffect, useState} from 'react';
import {Alert, Linking, StyleSheet, Text, TextInput, TouchableOpacity, View} from 'react-native';

import {api} from '../api';
import PinField from '../components/PinField';
import Segments from '../components/Segments';
import {playSound, signActionCode, signBalanceCode, unlock} from '../native';
import {Session, t} from '../session';
import {colors, ui} from '../theme';

// Track: payment history, autopays, shop orders and deliveries in one place.

const FAILED = ['FAILED', 'DENIED', 'RETURNED', 'BLOCKED', 'REVERSED', 'CANCELLED', 'EXPIRED'];
const ATTENTION = ['UNCLAIMED', 'UNKNOWN', 'ONHOLD', 'APPROVAL_PENDING', 'SUSPENDED', 'CREATED', 'DUE'];

type Section = 'payments' | 'autopay' | 'orders' | 'deliveries';
const INTERVALS = [
  {value: 'WEEK', en: 'Every week', ta: 'வாரந்தோறும்'},
  {value: 'MONTH', en: 'Every month', ta: 'மாதந்தோறும்'},
  {value: 'YEAR', en: 'Every year', ta: 'ஆண்டுதோறும்'},
];

const day = (iso?: string | null) =>
  iso ? new Date(iso).toLocaleDateString('en-GB', {day: '2-digit', month: 'short', year: 'numeric'}) : '';

const inDays = (days: number) => {
  const d = new Date();
  d.setDate(d.getDate() + days);
  return d.toISOString().slice(0, 10);
};

const STATUS_WORDS: Record<string, string> = {
  ACTIVE: 'Active',
  APPROVAL_PENDING: 'Waiting for your approval in PayPal',
  SUSPENDED: 'Paused',
  CANCELLED: 'Cancelled',
  EXPIRED: 'Ended',
};

const HistoryScreen = ({session}: {session: Session}) => {
  const {account, tamil} = session;
  // Private: unlock with fingerprint / PIN once per app session.
  const [unlocked, setUnlocked] = useState(false);
  const [section, setSection] = useState<Section>('payments');
  const [track, setTrack] = useState<any>(null);
  const [owner, setOwner] = useState<any>(null);
  const [message, setMessage] = useState('');
  const [balance, setBalance] = useState('');
  const [balancePin, setBalancePin] = useState('');
  const [autopayPin, setAutopayPin] = useState('');
  const [busy, setBusy] = useState(false);
  // "Add an autopay you pay elsewhere"
  const [adding, setAdding] = useState(false);
  const [name, setName] = useState('');
  const [amount, setAmount] = useState('');
  const [every, setEvery] = useState('MONTH');
  const [nextDate, setNextDate] = useState(inDays(30));

  const load = useCallback(async () => {
    if (!account) {
      return;
    }
    setMessage('');
    try {
      setTrack(await api('/api/track', account.token));
      if (account.isOwner) {
        setOwner(await api('/api/history', account.token));
      }
    } catch (error) {
      setMessage(session.handleError(error));
    }
  }, [account, session]);

  useEffect(() => {
    if (unlocked) {
      load();
    }
  }, [unlocked, load]);

  // The server only answers for the PayGuard PIN plus a fresh fingerprint signature.
  const checkBalance = async () => {
    if (!account) {
      return;
    }
    const pin = balancePin;
    setBalancePin('');
    if (pin.length < 4) {
      setBalance(t(tamil, 'Please type your PayGuard PIN first.', 'முதலில் உங்கள் PayGuard PIN-ஐ தட்டச்சு செய்யுங்கள்.'));
      return;
    }
    setBalance('…');
    try {
      const {challenge} = await api('/api/security/balance-challenge', account.token);
      const signature = await signBalanceCode(challenge);
      const result = await api('/api/security/balance', account.token, {body: {challenge, signature, pin}});
      const lines = result.balances.map(
        (b: any) => `${b.currency} ${b.available} ${t(tamil, 'available', 'கிடைக்கிறது')}` +
          (Number(b.on_hold) > 0 ? ` (${b.on_hold} ${t(tamil, 'on hold', 'நிறுத்திவைப்பில்')})` : ''),
      );
      setBalance(lines.join('\n') || t(tamil, 'No balance.', 'இருப்பு இல்லை.'));
      playSound('unlocked');
    } catch (error) {
      setBalance(error instanceof Error ? error.message : session.handleError(error));
    }
  };

  const run = async (work: () => Promise<string | void>) => {
    setBusy(true);
    setMessage('');
    try {
      const done = await work();
      await load();
      if (done) {
        setMessage(done);
      }
    } catch (error) {
      setMessage(session.handleError(error));
      playSound('failed');
    } finally {
      setBusy(false);
    }
  };

  const startAutopay = (biller: any) =>
    run(async () => {
      const item = await api('/api/autopay/start', account!.token, {body: {biller: biller.key}});
      playSound('request_sent');
      await Linking.openURL(item.approval_url);
      return t(tamil, `Approve ${item.name} in PayPal. PayGuard checks it when you come back.`,
        `${item.name}-ஐ PayPal-இல் அனுமதியுங்கள்.`);
    });

  const changeAutopay = (item: any, what: 'cancel' | 'pause' | 'resume') => {
    const pin = autopayPin;
    if (pin.length < 4) {
      setMessage(t(tamil, 'Type your PayGuard PIN above the autopays first.', 'முதலில் PayGuard PIN-ஐ தட்டச்சு செய்யுங்கள்.'));
      return;
    }
    const go = () =>
      run(async () => {
        setAutopayPin('');
        const {challenge} = await api('/api/security/challenge', account!.token);
        const signature = await signActionCode(challenge, `${what} ${item.name} autopay`);
        const updated = await api(`/api/autopay/${item.id}/${what}`, account!.token, {
          body: {pin, challenge, signature},
        });
        playSound('request_sent');
        return `${updated.name}: ${STATUS_WORDS[updated.status] ?? updated.status}.`;
      });
    if (what === 'cancel') {
      Alert.alert(
        t(tamil, 'Cancel autopay?', 'தானியங்கி கட்டணத்தை ரத்து செய்யவா?'),
        `${item.name}, $${item.amount} every ${item.every}`,
        [
          {text: t(tamil, 'Keep it', 'வைத்திரு'), style: 'cancel'},
          {text: t(tamil, 'Cancel autopay', 'ரத்து செய்'), style: 'destructive', onPress: go},
        ],
      );
    } else {
      go();
    }
  };

  const addManual = () =>
    run(async () => {
      const value = Number(amount.replace(',', '.'));
      if (name.trim().length < 2 || !Number.isFinite(value) || value <= 0) {
        throw new Error(t(tamil, 'Please give a name and an amount.', 'பெயரும் தொகையும் தேவை.'));
      }
      const item = await api('/api/autopay/manual', account!.token, {
        body: {name: name.trim(), amount: value.toFixed(2), interval: every, next_date: nextDate},
      });
      setAdding(false);
      setName('');
      setAmount('');
      playSound('request_sent');
      return t(tamil, `Added ${item.name}. PayGuard will remind you 2 days before ${item.next_date}.`,
        `${item.name} சேர்க்கப்பட்டது.`);
    });

  if (!account) {
    return (
      <View style={ui.card}>
        <Text style={ui.body}>{t(tamil, 'Please log in on the Home tab first.', 'முதலில் முகப்பில் உள்நுழையுங்கள்.')}</Text>
      </View>
    );
  }

  if (!unlocked) {
    return (
      <View style={ui.card}>
        <Text style={ui.title} accessibilityRole="header">
          {t(tamil, 'Track is locked', 'கண்காணிப்பு பூட்டப்பட்டுள்ளது')}
        </Text>
        <Text style={ui.body}>
          {t(tamil, 'Use your fingerprint, face or phone PIN to see your payments, autopays, orders and deliveries.',
            'உங்கள் கட்டணங்கள், தானியங்கி கட்டணங்கள், ஆர்டர்களைப் பார்க்க கைரேகை அல்லது PIN பயன்படுத்துங்கள்.')}
        </Text>
        <TouchableOpacity
          onPress={async () => {
            const ok = await unlock(t(tamil, 'See your payments and orders', 'கட்டணங்களைப் பார்க்க'));
            if (ok) {
              setUnlocked(true);
            } else {
              setMessage(t(tamil, 'Not unlocked.', 'திறக்கப்படவில்லை.'));
            }
          }}
          accessibilityRole="button"
          style={ui.primaryButton}>
          <Text style={ui.primaryButtonText}>{t(tamil, 'Unlock Track', 'திற')}</Text>
        </TouchableOpacity>
        {message ? <Text style={ui.error}>{message}</Text> : null}
      </View>
    );
  }

  const row = (key: string, title: string, detail: string, status?: string, extra?: React.ReactNode) => {
    const bad = status && FAILED.includes(status);
    const warn = status && ATTENTION.includes(status);
    return (
      <View key={key} style={[styles.row, bad && styles.bad, warn && styles.warn]}>
        <View accessible>
          <Text style={styles.rowTitle}>{title}</Text>
          <Text style={[ui.muted, bad && styles.badText]}>{detail}</Text>
        </View>
        {extra}
      </View>
    );
  };

  const small = (label: string, onPress: () => void, a11y?: string) => (
    <TouchableOpacity
      key={label}
      onPress={onPress}
      disabled={busy}
      accessibilityRole="button"
      accessibilityLabel={a11y ?? label}
      style={styles.small}>
      <Text style={styles.smallText}>{label}</Text>
    </TouchableOpacity>
  );

  const SECTIONS: {key: Section; en: string; ta: string}[] = [
    {key: 'payments', en: 'Payments', ta: 'கட்டணங்கள்'},
    {key: 'autopay', en: 'Autopay', ta: 'தானியங்கி'},
    {key: 'orders', en: 'Orders', ta: 'ஆர்டர்கள்'},
    {key: 'deliveries', en: 'Deliveries', ta: 'டெலிவரி'},
  ];

  const payments = track?.payments ?? [];
  const autopays = track?.autopays ?? [];
  const orders = track?.orders ?? [];
  const deliveries = track?.deliveries ?? [];

  return (
    <View>
      <Segments
        value={section}
        onChange={setSection}
        items={SECTIONS.map(s => ({key: s.key, label: t(tamil, s.en, s.ta)}))}
      />

      <TouchableOpacity onPress={load} accessibilityRole="button" style={[ui.secondaryButton, styles.refresh]}>
        <Text style={ui.secondaryButtonText}>{t(tamil, 'Refresh', 'புதுப்பி')}</Text>
      </TouchableOpacity>
      {message ? (
        <Text style={[ui.body, styles.message]} accessibilityLiveRegion="polite">
          {message}
        </Text>
      ) : null}
      {!track && !message ? <Text style={ui.muted}>{t(tamil, 'Loading…', 'ஏற்றுகிறது…')}</Text> : null}

      {section === 'payments' && track && (
        <>
          {account.isOwner && (
            <View style={ui.card}>
              <Text style={ui.heading} accessibilityRole="header">
                {t(tamil, 'PayPal balance', 'PayPal இருப்பு')}
              </Text>
              <Text style={ui.muted}>
                {t(tamil, 'Money in the PayGuard wallet (the PayPal account PayGuard manages).',
                  'PayGuard நிர்வகிக்கும் PayPal கணக்கில் உள்ள பணம்.')}
              </Text>
              {balance ? (
                <Text style={[ui.title, styles.balance]} accessibilityLiveRegion="polite">
                  {balance}
                </Text>
              ) : null}
              <PinField label="PayGuard PIN" value={balancePin} onChange={setBalancePin} onDone={checkBalance} />
              <TouchableOpacity onPress={checkBalance} accessibilityRole="button" style={ui.primaryButton}>
                <Text style={ui.primaryButtonText}>{t(tamil, 'Check balance', 'இருப்பைப் பார்')}</Text>
              </TouchableOpacity>
            </View>
          )}

          {account.isOwner && owner?.requests?.length > 0 && (
            <View style={ui.card}>
              <Text style={ui.heading} accessibilityRole="header">
                {t(tamil, 'Refund requests', 'பணத்திருப்பக் கோரிக்கைகள்')}
              </Text>
              {owner.requests.map((r: any) =>
                row(`r${r.number}`, `${t(tamil, 'Request', 'கோரிக்கை')} ${r.number}: $${r.amount}`,
                  `${r.customer}: "${r.reason}"`, 'ONHOLD'),
              )}
            </View>
          )}

          <View style={ui.card}>
            <Text style={ui.heading} accessibilityRole="header">
              {t(tamil, 'Payment history', 'கட்டண வரலாறு')}
            </Text>
            {payments.length === 0 && (
              <Text style={ui.muted}>{t(tamil, 'No payments yet.', 'இன்னும் கட்டணங்கள் இல்லை.')}</Text>
            )}
            {payments.map((p: any, i: number) =>
              row(`p${i}`, p.title, `${day(p.date)} · ${p.status_text}`, p.status),
            )}
          </View>
        </>
      )}

      {section === 'autopay' && track && (
        <>
          <View style={ui.card}>
            <Text style={ui.heading} accessibilityRole="header">
              {t(tamil, 'Your autopays', 'உங்கள் தானியங்கி கட்டணங்கள்')}
            </Text>
            {autopays.length === 0 && (
              <Text style={ui.muted}>{t(tamil, 'No autopays yet.', 'இன்னும் இல்லை.')}</Text>
            )}
            {autopays.some((a: any) => a.status !== 'CANCELLED' && a.status !== 'EXPIRED') && (
              <PinField
                label={t(tamil, 'PayGuard PIN to pause, resume or cancel', 'மாற்ற PayGuard PIN')}
                value={autopayPin}
                onChange={setAutopayPin}
              />
            )}
            {autopays.map((a: any) =>
              row(
                `a${a.id}`,
                `${a.number}. ${a.name}: $${a.amount} every ${a.every}`,
                [
                  STATUS_WORDS[a.status] ?? a.status,
                  a.status === 'ACTIVE' && a.next_date ? `next ${day(a.next_date)}` : '',
                  a.last_paid_at ? `last paid ${day(a.last_paid_at)}` : '',
                  a.failed_count ? `${a.failed_count} failed` : '',
                  a.source === 'manual' ? t(tamil, 'added by you, reminder only', 'நீங்கள் சேர்த்தது') : 'PayPal',
                ].filter(Boolean).join(' · '),
                a.status,
                a.status === 'CANCELLED' || a.status === 'EXPIRED' ? null : (
                  <View style={styles.actions}>
                    {a.status === 'APPROVAL_PENDING' && a.approval_url &&
                      small(t(tamil, 'Approve in PayPal', 'PayPal-இல் அனுமதி'), () => Linking.openURL(a.approval_url),
                        `Approve ${a.name} in PayPal`)}
                    {a.status === 'APPROVAL_PENDING' &&
                      small(t(tamil, 'Check again', 'மீண்டும் சரிபார்'),
                        () => run(async () => {
                          await api(`/api/autopay/${a.id}/refresh`, account.token, {body: {}});
                        }),
                        `Check ${a.name} again`)}
                    {a.status === 'ACTIVE' &&
                      small(t(tamil, 'Pause', 'இடைநிறுத்து'), () => changeAutopay(a, 'pause'), `Pause ${a.name}`)}
                    {a.status === 'SUSPENDED' &&
                      small(t(tamil, 'Resume', 'தொடர்'), () => changeAutopay(a, 'resume'), `Resume ${a.name}`)}
                    {small(t(tamil, 'Cancel', 'ரத்து'), () => changeAutopay(a, 'cancel'), `Cancel ${a.name} autopay`)}
                  </View>
                ),
              ),
            )}
          </View>

          <View style={ui.card}>
            <Text style={ui.heading} accessibilityRole="header">
              {t(tamil, 'Start an autopay with PayPal', 'PayPal மூலம் தானியங்கி கட்டணம் தொடங்கு')}
            </Text>
            <Text style={ui.muted}>
              {t(tamil, 'Demo billers (sandbox). You approve it in PayPal; PayPal charges it until you cancel, and PayGuard alerts you each time.',
                'சோதனை நிறுவனங்கள். PayPal-இல் அனுமதிப்பீர்கள்; ஒவ்வொரு முறையும் PayGuard தெரிவிக்கும்.')}
            </Text>
            {(track.billers ?? []).map((b: any) => (
              <TouchableOpacity
                key={b.key}
                onPress={() => startAutopay(b)}
                disabled={busy}
                accessibilityRole="button"
                accessibilityLabel={`Start ${b.name} autopay, $${b.amount} every ${b.every}`}
                style={ui.secondaryButton}>
                <Text style={ui.secondaryButtonText}>{`${b.name}: $${b.amount} / ${b.every}`}</Text>
              </TouchableOpacity>
            ))}
          </View>

          <View style={ui.card}>
            <Text style={ui.heading} accessibilityRole="header">
              {t(tamil, 'Add an autopay you pay elsewhere', 'வேறு இடத்தில் உள்ள தானியங்கி கட்டணம்')}
            </Text>
            <Text style={ui.muted}>
              {t(tamil, 'PayPal does not show apps your autopays with other companies, so add them here. PayGuard reminds you 2 days before each charge.',
                'மற்ற நிறுவனங்களின் தானியங்கி கட்டணங்களை PayPal காட்டாது; இங்கே சேர்க்கவும். 2 நாள் முன் நினைவூட்டும்.')}
            </Text>
            {!adding ? (
              <TouchableOpacity onPress={() => setAdding(true)} accessibilityRole="button" style={ui.secondaryButton}>
                <Text style={ui.secondaryButtonText}>{t(tamil, 'Add an autopay', 'சேர்')}</Text>
              </TouchableOpacity>
            ) : (
              <>
                <Text style={ui.label} nativeID="apName">{t(tamil, 'Name, for example Phone bill', 'பெயர்')}</Text>
                <TextInput value={name} onChangeText={setName} accessibilityLabelledBy="apName" maxLength={60} style={ui.input} />
                <Text style={ui.label} nativeID="apAmount">{t(tamil, 'Amount in US dollars', 'தொகை (டாலர்)')}</Text>
                <TextInput
                  value={amount}
                  onChangeText={setAmount}
                  accessibilityLabelledBy="apAmount"
                  keyboardType="decimal-pad"
                  maxLength={8}
                  style={ui.input}
                />
                <Text style={ui.label} nativeID="apEvery">{t(tamil, 'How often', 'எவ்வளவு அடிக்கடி')}</Text>
                <View style={styles.actions} accessibilityRole="radiogroup" accessibilityLabelledBy="apEvery">
                  {INTERVALS.map(option => (
                    <TouchableOpacity
                      key={option.value}
                      onPress={() => setEvery(option.value)}
                      accessibilityRole="radio"
                      accessibilityState={{checked: every === option.value}}
                      style={[styles.small, every === option.value && styles.smallSelected]}>
                      <Text style={styles.smallText}>{t(tamil, option.en, option.ta)}</Text>
                    </TouchableOpacity>
                  ))}
                </View>
                <Text style={ui.label} nativeID="apDate">
                  {t(tamil, 'Next payment date (year-month-day)', 'அடுத்த கட்டணத் தேதி')}
                </Text>
                <TextInput value={nextDate} onChangeText={setNextDate} accessibilityLabelledBy="apDate" maxLength={10} style={ui.input} />
                <TouchableOpacity onPress={addManual} disabled={busy} accessibilityRole="button" style={ui.primaryButton}>
                  <Text style={ui.primaryButtonText}>{t(tamil, 'Save autopay', 'சேமி')}</Text>
                </TouchableOpacity>
                <TouchableOpacity onPress={() => setAdding(false)} accessibilityRole="button" style={ui.secondaryButton}>
                  <Text style={ui.secondaryButtonText}>{t(tamil, 'Cancel', 'ரத்து')}</Text>
                </TouchableOpacity>
              </>
            )}
          </View>
        </>
      )}

      {section === 'orders' && track && (
        <View style={ui.card}>
          <Text style={ui.heading} accessibilityRole="header">
            {t(tamil, 'Shopping orders', 'ஷாப்பிங் ஆர்டர்கள்')}
          </Text>
          {orders.length === 0 && <Text style={ui.muted}>{t(tamil, 'No orders yet.', 'இன்னும் ஆர்டர்கள் இல்லை.')}</Text>}
          {orders.map((o: any) =>
            row(
              `o${o.code}`,
              `${t(tamil, 'Order', 'ஆர்டர்')} ${o.code}: ${o.name}`,
              `$${o.total} · ${o.status === 'PAID'
                ? `${t(tamil, 'paid', 'செலுத்தப்பட்டது')} ${day(o.paid_at || o.created_at)}`
                : t(tamil, 'not paid yet', 'இன்னும் செலுத்தவில்லை')}`,
              o.status === 'PAID' ? undefined : 'CREATED',
              <View style={styles.actions}>
                {o.status === 'PAID'
                  ? small(t(tamil, 'Receipt in Shop', 'ரசீது'), () => session.goTo('shop'), `Open receipt for order ${o.code} in Shop`)
                  : o.approval_url
                    ? small(t(tamil, 'Pay with PayPal', 'PayPal மூலம் செலுத்து'), () => Linking.openURL(o.approval_url),
                      `Pay order ${o.code} with PayPal`)
                    : null}
              </View>,
            ),
          )}
        </View>
      )}

      {section === 'deliveries' && track && (
        <View style={ui.card}>
          <Text style={ui.heading} accessibilityRole="header">
            {t(tamil, 'Deliveries', 'டெலிவரி')}
          </Text>
          <Text style={ui.muted}>
            {t(tamil, 'Expected dates from the shop (no live courier tracking in the demo).', 'கடை தந்த எதிர்பார்க்கப்படும் தேதிகள்.')}
          </Text>
          {deliveries.length === 0 && (
            <Text style={ui.muted}>{t(tamil, 'Nothing on the way.', 'வருவதற்கு எதுவும் இல்லை.')}</Text>
          )}
          {deliveries.map((d: any) =>
            row(`d${d.code}`, `${t(tamil, 'Order', 'ஆர்டர்')} ${d.code}: ${d.name}`, d.status_text, d.status),
          )}
        </View>
      )}
    </View>
  );
};

const styles = StyleSheet.create({
  sections: {
    flexDirection: 'row',
    backgroundColor: colors.card,
    borderRadius: 12,
    padding: 4,
    marginBottom: 12,
    borderWidth: 1,
    borderColor: colors.line,
  },
  section: {
    flex: 1,
    paddingVertical: 12,
    borderRadius: 9,
    alignItems: 'center',
  },
  sectionSelected: {
    backgroundColor: colors.navy,
  },
  sectionText: {
    color: colors.ink,
    fontSize: 14,
    fontWeight: '700',
  },
  sectionTextSelected: {
    color: '#FFFFFF',
  },
  balance: {
    marginTop: 12,
    marginBottom: 0,
  },
  refresh: {
    marginTop: 0,
    marginBottom: 12,
  },
  message: {
    marginBottom: 12,
  },
  row: {
    borderLeftWidth: 4,
    borderLeftColor: colors.line,
    paddingVertical: 8,
    paddingHorizontal: 12,
    marginBottom: 8,
    backgroundColor: '#F8FAFC',
    borderRadius: 8,
  },
  bad: {
    borderLeftColor: colors.bad,
    backgroundColor: colors.badBg,
  },
  warn: {
    borderLeftColor: '#F59E0B',
    backgroundColor: colors.warnBg,
  },
  rowTitle: {
    color: colors.ink,
    fontSize: 17,
    fontWeight: '700',
  },
  badText: {
    color: colors.bad,
  },
  actions: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 8,
    marginTop: 8,
  },
  small: {
    borderWidth: 1,
    borderColor: colors.line,
    backgroundColor: colors.card,
    borderRadius: 10,
    paddingVertical: 10,
    paddingHorizontal: 12,
    minHeight: 44,
    justifyContent: 'center',
  },
  smallSelected: {
    borderColor: colors.brand,
    borderWidth: 2,
    backgroundColor: colors.brandSoft,
  },
  smallText: {
    color: colors.ink,
    fontSize: 15,
    fontWeight: '700',
  },
});

export default HistoryScreen;
