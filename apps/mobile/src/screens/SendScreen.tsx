import React, {useCallback, useEffect, useState} from 'react';
import {StyleSheet, Text, TextInput, TouchableOpacity, View} from 'react-native';

import {api, AssistantReply, PendingAction} from '../api';
import ConfirmBox from '../components/ConfirmBox';
import {playSound} from '../native';
import {confirmWithSecurity, Session, t} from '../session';
import {colors, ui} from '../theme';

type Contact = {name: string; email: string};

const SendScreen = ({session}: {session: Session}) => {
  const {account, tamil} = session;
  const [contacts, setContacts] = useState<Contact[]>([]);
  const [leftToday, setLeftToday] = useState('');
  const [chosen, setChosen] = useState<Contact | null>(null);
  const [amount, setAmount] = useState('');
  const [pending, setPending] = useState<PendingAction | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');

  const load = useCallback(async () => {
    if (!account?.isOwner) {
      return;
    }
    try {
      const data = await api('/api/contacts', account.token);
      setContacts(data.contacts);
      setLeftToday(data.left_today);
    } catch (error) {
      setMessage(session.handleError(error));
    }
  }, [account, session]);

  useEffect(() => {
    load();
  }, [load]);

  if (!account) {
    return (
      <View style={ui.card}>
        <Text style={ui.body}>{t(tamil, 'Please log in on the Home tab first.', 'முதலில் முகப்பில் உள்நுழையுங்கள்.')}</Text>
      </View>
    );
  }

  if (!account.isOwner) {
    return (
      <View style={ui.card}>
        <Text style={ui.heading} accessibilityRole="header">
          {t(tamil, 'Send money', 'பணம் அனுப்பு')}
        </Text>
        <Text style={ui.body}>
          {t(
            tamil,
            'Only the account owner can send money from this PayPal wallet. You can see your purchases in History and ask for refunds in the Assistant.',
            'இந்த PayPal கணக்கிலிருந்து உரிமையாளர் மட்டுமே பணம் அனுப்ப முடியும். உங்கள் வாங்குதல்களை வரலாற்றில் பார்க்கலாம்.',
          )}
        </Text>
      </View>
    );
  }

  const review = async () => {
    setMessage('');
    const value = Number(amount.replace(',', '.'));
    if (!chosen) {
      setMessage(t(tamil, 'Choose who to send money to.', 'யாருக்கு அனுப்ப வேண்டும் என்று தேர்ந்தெடுங்கள்.'));
      return;
    }
    if (!Number.isFinite(value) || value <= 0) {
      setMessage(t(tamil, 'Enter an amount, for example 20.', 'தொகையை உள்ளிடுங்கள், எ.கா. 20.'));
      return;
    }
    setBusy(true);
    try {
      const reply = await api<AssistantReply>('/api/payouts/prepare', account.token, {
        body: {email: chosen.email, amount: value.toFixed(2)},
      });
      setPending(reply.pending_action);
      if (reply.pending_action) {
        playSound('confirm_needed');
      } else {
        setMessage(reply.reply);
        playSound('failed');
      }
    } catch (error) {
      setMessage(session.handleError(error));
    } finally {
      setBusy(false);
    }
  };

  const confirm = async () => {
    if (!pending) {
      return;
    }
    setBusy(true);
    try {
      const reply = await confirmWithSecurity(account.token, pending);
      setPending(null);
      setMessage(reply.reply);
      if (reply.event === 'payment_sent') {
        setAmount('');
        setChosen(null);
        load();
      }
    } catch (error) {
      const text = error instanceof Error && error.message ? error.message : 'Not confirmed.';
      setMessage(`${text} ${t(tamil, 'Nothing was sent.', 'எதுவும் அனுப்பப்படவில்லை.')}`);
    } finally {
      setBusy(false);
    }
  };

  const cancel = async () => {
    setPending(null);
    setMessage(t(tamil, 'Cancelled. Nothing was sent.', 'ரத்து செய்யப்பட்டது. எதுவும் அனுப்பப்படவில்லை.'));
    api('/api/chat/cancel', account.token, {body: {}}).catch(() => {});
  };

  return (
    <View>
      <View style={ui.card}>
        <Text style={ui.title} accessibilityRole="header">
          {t(tamil, 'Send money', 'பணம் அனுப்பு')}
        </Text>
        <Text style={ui.muted}>
          {t(tamil, `You can send $${leftToday || '…'} more today (up to $100 at a time).`,
            `இன்று இன்னும் $${leftToday || '…'} அனுப்பலாம் (ஒருமுறை $100 வரை).`)}
        </Text>

        <Text style={ui.label} nativeID="toLabel">
          {t(tamil, 'To', 'யாருக்கு')}
        </Text>
        <View accessibilityRole="radiogroup" accessibilityLabelledBy="toLabel">
          {contacts.map(contact => {
            const selected = chosen?.email === contact.email;
            return (
              <TouchableOpacity
                key={contact.email}
                onPress={() => setChosen(contact)}
                accessibilityRole="radio"
                accessibilityState={{checked: selected}}
                style={[styles.contact, selected && styles.contactSelected]}>
                <Text style={styles.radio}>{selected ? '◉' : '○'}</Text>
                <View style={styles.contactText}>
                  <Text style={styles.contactName}>{contact.name}</Text>
                  <Text style={ui.muted} numberOfLines={1}>
                    {contact.email}
                  </Text>
                </View>
              </TouchableOpacity>
            );
          })}
        </View>

        <Text style={ui.label} nativeID="amountLabel">
          {t(tamil, 'Amount in US dollars', 'தொகை (அமெரிக்க டாலர்)')}
        </Text>
        <TextInput
          value={amount}
          onChangeText={setAmount}
          accessibilityLabelledBy="amountLabel"
          keyboardType="decimal-pad"
          maxLength={6}
          style={ui.input}
        />

        {!pending && (
          <TouchableOpacity
            onPress={review}
            disabled={busy}
            accessibilityRole="button"
            accessibilityState={{disabled: busy, busy}}
            style={[ui.primaryButton, busy && ui.disabled]}>
            <Text style={ui.primaryButtonText}>{t(tamil, 'Review payment', 'கட்டணத்தைச் சரிபார்')}</Text>
          </TouchableOpacity>
        )}

        {pending && <ConfirmBox action={pending} busy={busy} onConfirm={confirm} onCancel={cancel} />}

        {message ? (
          <Text style={[ui.body, styles.message]} accessibilityLiveRegion="polite">
            {message}
          </Text>
        ) : null}
      </View>
    </View>
  );
};

const styles = StyleSheet.create({
  contact: {
    flexDirection: 'row',
    alignItems: 'center',
    borderWidth: 1,
    borderColor: colors.line,
    borderRadius: 12,
    padding: 12,
    marginBottom: 8,
  },
  contactSelected: {
    borderColor: colors.brandBlue,
    borderWidth: 2,
    backgroundColor: '#E8F0FE',
  },
  radio: {
    fontSize: 22,
    marginRight: 12,
    color: colors.brandBlue,
  },
  contactText: {
    flex: 1,
  },
  contactName: {
    color: colors.ink,
    fontSize: 17,
    fontWeight: '700',
  },
  message: {
    marginTop: 14,
  },
});

export default SendScreen;
