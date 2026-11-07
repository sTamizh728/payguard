import React, {useCallback, useEffect, useState} from 'react';
import {Linking, StyleSheet, Text, TextInput, TouchableOpacity, View} from 'react-native';

import {api, AssistantReply, PendingAction} from '../api';
import ConfirmBox from '../components/ConfirmBox';
import {pickContactEmail, playSound} from '../native';
import {confirmWithSecurity, Session, t} from '../session';
import {colors, ui} from '../theme';

type Contact = {name: string; email: string};
// 'wallet': the PayGuard business wallet (owner only, PIN + fingerprint).
// 'own': the person's own PayPal account, approved on PayPal's page.
type Source = 'wallet' | 'own';

const SendScreen = ({session}: {session: Session}) => {
  const {account, tamil} = session;
  const [contacts, setContacts] = useState<Contact[]>([]);
  const [leftToday, setLeftToday] = useState('');
  const [chosen, setChosen] = useState<Contact | null>(null);
  const [amount, setAmount] = useState('');
  const [pending, setPending] = useState<PendingAction | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');
  const [source, setSource] = useState<Source>(account?.isOwner ? 'wallet' : 'own');
  const [newName, setNewName] = useState('');
  const [newEmail, setNewEmail] = useState('');

  const load = useCallback(async () => {
    if (!account) {
      return;
    }
    try {
      if (account.isOwner) {
        const data = await api('/api/contacts', account.token);
        setContacts(data.contacts);
        setLeftToday(data.left_today);
      } else {
        const data = await api('/api/pay/contacts', account.token);
        setContacts(data.contacts);
      }
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

  // Save someone (picked from the phone, or typed) as a PayGuard contact and choose them.
  const addContact = async (name: string, email: string) => {
    setMessage('');
    try {
      const saved = await api('/api/contacts/save', account.token, {body: {name, email}});
      await load();
      setChosen({name: saved.name, email: saved.email});
      setNewName('');
      setNewEmail('');
      setMessage(t(tamil, `${saved.name} is chosen.`, `${saved.name} தேர்ந்தெடுக்கப்பட்டார்.`));
    } catch (error) {
      setMessage(session.handleError(error));
      playSound('failed');
    }
  };

  const pickFromPhone = async () => {
    try {
      const picked = await pickContactEmail();
      if (picked?.email) {
        await addContact(picked.name, picked.email);
      } else if (picked) {
        setMessage(t(tamil, 'That contact has no email. Type their PayPal email below.',
          'அந்தத் தொடர்பில் மின்னஞ்சல் இல்லை. கீழே PayPal மின்னஞ்சலை உள்ளிடுங்கள்.'));
      }
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Could not open contacts.');
    }
  };

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
    if (source === 'own') {
      try {
        const started = await api('/api/pay/start', account.token, {
          body: {email: chosen.email, amount: value.toFixed(2)},
        });
        setPending({
          id: String(started.id),
          type: 'checkout',
          summary: `Send $${started.amount} to ${started.name} from your PayPal`,
          url: started.approval_url,
        });
        playSound('confirm_needed');
      } catch (error) {
        setMessage(session.handleError(error));
        playSound('failed');
      } finally {
        setBusy(false);
      }
      return;
    }
    try {
      const reply = await api<AssistantReply>('/api/payouts/prepare', account.token, {
        body: {email: chosen.email, amount: value.toFixed(2)},
      });
      setPending(reply.pending_action);
      if (reply.pending_action?.warnings?.length) {
        setMessage(reply.reply);
        playSound('warning'); // low notes: scam warning signs
      } else if (reply.pending_action) {
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

  const confirm = async (pin: string) => {
    if (!pending) {
      return;
    }
    if (pending.type === 'checkout' && pending.url) {
      // PayPal's own page: PayPal logs the person in and they approve there.
      const url = pending.url;
      setPending(null);
      setMessage(t(tamil, 'Approve the payment in PayPal. PayGuard finishes it when you come back.',
        'PayPal-இல் அனுமதியுங்கள். திரும்பி வந்ததும் PayGuard முடிக்கும்.'));
      playSound('request_sent');
      await Linking.openURL(url);
      return;
    }
    setBusy(true);
    try {
      const reply = await confirmWithSecurity(account.token, pending, pin);
      // Still waiting (scam guard cooling-off) keeps the box open.
      setPending(reply.pending_action);
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
        {account.isOwner && (
          <>
            <Text style={ui.label} nativeID="fromLabel">
              {t(tamil, 'Send from', 'எதிலிருந்து')}
            </Text>
            <View accessibilityRole="radiogroup" accessibilityLabelledBy="fromLabel">
              {([
                ['wallet', t(tamil, 'PayGuard wallet', 'PayGuard கணக்கு'),
                  t(tamil, 'Your PIN and fingerprint send it here', 'PIN, கைரேகை மூலம் இங்கேயே')],
                ['own', t(tamil, 'My own PayPal', 'என் சொந்த PayPal'),
                  t(tamil, 'You approve it on PayPal\'s page', 'PayPal பக்கத்தில் அனுமதிப்பீர்கள்')],
              ] as [Source, string, string][]).map(([value, label, hint]) => {
                const selected = source === value;
                return (
                  <TouchableOpacity
                    key={value}
                    onPress={() => {
                      setSource(value);
                      setPending(null);
                    }}
                    accessibilityRole="radio"
                    accessibilityState={{checked: selected}}
                    accessibilityHint={hint}
                    style={[styles.contact, selected && styles.contactSelected]}>
                    <Text style={styles.radio}>{selected ? '◉' : '○'}</Text>
                    <View style={styles.contactText}>
                      <Text style={styles.contactName}>{label}</Text>
                      <Text style={ui.muted}>{hint}</Text>
                    </View>
                  </TouchableOpacity>
                );
              })}
            </View>
          </>
        )}
        <Text style={ui.muted}>
          {source === 'wallet'
            ? t(tamil, `You can send $${leftToday || '…'} more today (up to $100 at a time).`,
              `இன்று இன்னும் $${leftToday || '…'} அனுப்பலாம் (ஒருமுறை $100 வரை).`)
            : t(tamil, 'Paid from your own PayPal account, up to $100 at a time. PayPal will ask you to log in and approve.',
              'உங்கள் சொந்த PayPal கணக்கிலிருந்து, ஒருமுறை $100 வரை. PayPal உள்நுழைந்து அனுமதிக்கக் கேட்கும்.')}
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

        <TouchableOpacity onPress={pickFromPhone} accessibilityRole="button" style={ui.secondaryButton}>
          <Text style={ui.secondaryButtonText}>📇 {t(tamil, 'Pick from phone contacts', 'போன் தொடர்புகளிலிருந்து தேர்வு')}</Text>
        </TouchableOpacity>

        <Text style={ui.label} nativeID="newEmailLabel">
          {t(tamil, 'Or type their PayPal email', 'அல்லது அவர்களின் PayPal மின்னஞ்சல்')}
        </Text>
        <TextInput
          value={newEmail}
          onChangeText={setNewEmail}
          accessibilityLabelledBy="newEmailLabel"
          keyboardType="email-address"
          autoCapitalize="none"
          autoCorrect={false}
          maxLength={255}
          style={ui.input}
        />
        <Text style={ui.label} nativeID="newNameLabel">
          {t(tamil, 'Their name (optional)', 'அவர்கள் பெயர் (விருப்பம்)')}
        </Text>
        <TextInput value={newName} onChangeText={setNewName} accessibilityLabelledBy="newNameLabel" maxLength={100} style={ui.input} />
        <TouchableOpacity
          onPress={() => addContact(newName, newEmail)}
          disabled={newEmail.trim().length < 3}
          accessibilityRole="button"
          accessibilityState={{disabled: newEmail.trim().length < 3}}
          style={[ui.secondaryButton, newEmail.trim().length < 3 && ui.disabled]}>
          <Text style={ui.secondaryButtonText}>＋ {t(tamil, 'Add and choose', 'சேர்த்து தேர்வு செய்')}</Text>
        </TouchableOpacity>

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
