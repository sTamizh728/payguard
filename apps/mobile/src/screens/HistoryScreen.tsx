import React, {useCallback, useEffect, useState} from 'react';
import {StyleSheet, Text, TouchableOpacity, View} from 'react-native';

import {api} from '../api';
import {unlock} from '../native';
import {Session, t} from '../session';
import {colors, ui} from '../theme';

const FAILED = ['FAILED', 'DENIED', 'RETURNED', 'BLOCKED', 'REVERSED'];
const ATTENTION = ['UNCLAIMED', 'UNKNOWN', 'ONHOLD'];

const day = (iso: string) =>
  new Date(iso).toLocaleDateString('en-GB', {day: '2-digit', month: 'short'});

const HistoryScreen = ({session}: {session: Session}) => {
  const {account, tamil} = session;
  // History is private: unlock with fingerprint / PIN once per app session.
  const [unlocked, setUnlocked] = useState(false);
  const [data, setData] = useState<any>(null);
  const [message, setMessage] = useState('');

  const load = useCallback(async () => {
    if (!account) {
      return;
    }
    setMessage('');
    try {
      setData(await api('/api/history', account.token));
    } catch (error) {
      setMessage(session.handleError(error));
    }
  }, [account, session]);

  useEffect(() => {
    if (unlocked) {
      load();
    }
  }, [unlocked, load]);

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
          {t(tamil, 'History is locked', 'வரலாறு பூட்டப்பட்டுள்ளது')}
        </Text>
        <Text style={ui.body}>
          {t(tamil, 'Use your fingerprint, face or phone PIN to see your payments.',
            'உங்கள் கட்டணங்களைப் பார்க்க கைரேகை, முகம் அல்லது PIN பயன்படுத்துங்கள்.')}
        </Text>
        <TouchableOpacity
          onPress={async () => {
            const ok = await unlock(t(tamil, 'See your payment history', 'கட்டண வரலாற்றைப் பார்க்க'));
            if (ok) {
              setUnlocked(true);
            } else {
              setMessage(t(tamil, 'Not unlocked.', 'திறக்கப்படவில்லை.'));
            }
          }}
          accessibilityRole="button"
          style={ui.primaryButton}>
          <Text style={ui.primaryButtonText}>🔒 {t(tamil, 'Unlock history', 'வரலாற்றைத் திற')}</Text>
        </TouchableOpacity>
        {message ? <Text style={ui.error}>{message}</Text> : null}
      </View>
    );
  }

  const row = (key: string, title: string, detail: string, status?: string) => {
    const bad = status && FAILED.includes(status);
    const warn = status && ATTENTION.includes(status);
    return (
      <View key={key} style={[styles.row, bad && styles.bad, warn && styles.warn]} accessible>
        <Text style={styles.rowTitle}>{title}</Text>
        <Text style={[ui.muted, bad && styles.badText]}>{detail}</Text>
      </View>
    );
  };

  return (
    <View>
      <TouchableOpacity onPress={load} accessibilityRole="button" style={[ui.secondaryButton, styles.refresh]}>
        <Text style={ui.secondaryButtonText}>↻ {t(tamil, 'Refresh', 'புதுப்பி')}</Text>
      </TouchableOpacity>
      {message ? <Text style={ui.error}>{message}</Text> : null}

      {data?.role === 'owner' && (
        <>
          <View style={ui.card}>
            <Text style={ui.heading} accessibilityRole="header">
              {t(tamil, 'Money you sent', 'நீங்கள் அனுப்பியது')}
            </Text>
            {data.sent.length === 0 && <Text style={ui.muted}>{t(tamil, 'Nothing sent yet.', 'இன்னும் எதுவும் அனுப்பவில்லை.')}</Text>}
            {data.sent.map((p: any) =>
              row(`s${p.number}`, `$${p.amount} → ${p.name}`, `${day(p.created_at)} · ${p.status_text}`, p.status),
            )}
          </View>

          <View style={ui.card}>
            <Text style={ui.heading} accessibilityRole="header">
              {t(tamil, 'Refund requests', 'பணத்திருப்பக் கோரிக்கைகள்')}
            </Text>
            {data.requests.length === 0 && <Text style={ui.muted}>{t(tamil, 'No open requests.', 'திறந்த கோரிக்கைகள் இல்லை.')}</Text>}
            {data.requests.map((r: any) =>
              row(`r${r.number}`, `${t(tamil, 'Request', 'கோரிக்கை')} ${r.number}: $${r.amount}`, `${r.customer}: "${r.reason}"`, 'ONHOLD'),
            )}
          </View>

          <View style={ui.card}>
            <Text style={ui.heading} accessibilityRole="header">
              {t(tamil, 'Money received', 'பெற்ற பணம்')}
            </Text>
            {data.received.map((p: any) =>
              row(
                `p${p.number}`,
                `${t(tamil, 'Payment', 'கட்டணம்')} ${p.number}: $${p.amount}`,
                `${day(p.created_at)} · ${Number(p.refundable) <= 0 ? t(tamil, 'fully refunded', 'முழுவதும் திருப்பப்பட்டது') : `$${p.refundable} ${t(tamil, 'can be refunded', 'திருப்பலாம்')}`}`,
              ),
            )}
          </View>
        </>
      )}

      {data?.role === 'customer' && (
        <View style={ui.card}>
          <Text style={ui.heading} accessibilityRole="header">
            {t(tamil, 'Your purchases', 'உங்கள் வாங்குதல்கள்')}
          </Text>
          {data.message ? <Text style={ui.muted}>{data.message}</Text> : null}
          {data.purchases.length === 0 && !data.message && (
            <Text style={ui.muted}>{t(tamil, 'No purchases yet.', 'இன்னும் வாங்குதல் இல்லை.')}</Text>
          )}
          {data.purchases.map((p: any) =>
            row(
              `c${p.number}`,
              `${t(tamil, 'Payment', 'கட்டணம்')} ${p.number}: $${p.amount}`,
              `${day(p.created_at)}${p.request_status ? ` · ${t(tamil, 'refund', 'பணத்திருப்பம்')}: ${p.request_status.toLowerCase()}` : ''}${Number(p.refundable) <= 0 ? ` · ${t(tamil, 'refunded', 'திருப்பப்பட்டது')}` : ''}`,
            ),
          )}
        </View>
      )}
    </View>
  );
};

const styles = StyleSheet.create({
  refresh: {
    marginTop: 0,
    marginBottom: 16,
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
});

export default HistoryScreen;
