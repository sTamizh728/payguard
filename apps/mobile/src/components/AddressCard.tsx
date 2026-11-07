import React, {useCallback, useEffect, useState} from 'react';
import {Text, TextInput, TouchableOpacity, View} from 'react-native';

import {api} from '../api';
import {playSound} from '../native';
import {t} from '../session';
import {ui} from '../theme';

type Address = {
  full_name: string;
  line1: string;
  line2?: string | null;
  city: string;
  state?: string | null;
  postal_code: string;
  country_code: string;
  phone?: string | null;
};

const EMPTY: Address = {full_name: '', line1: '', line2: '', city: '', state: '', postal_code: '', country_code: '', phone: ''};

const FIELDS: {key: keyof Address; en: string; ta: string; keyboard?: 'number-pad' | 'phone-pad'; max: number}[] = [
  {key: 'full_name', en: 'Full name', ta: 'முழுப் பெயர்', max: 100},
  {key: 'line1', en: 'House number and street', ta: 'வீட்டு எண், தெரு', max: 150},
  {key: 'line2', en: 'Area or landmark (optional)', ta: 'பகுதி / அடையாளம் (விருப்பம்)', max: 150},
  {key: 'city', en: 'City', ta: 'நகரம்', max: 80},
  {key: 'state', en: 'State', ta: 'மாநிலம்', max: 80},
  {key: 'postal_code', en: 'PIN code / postal code', ta: 'PIN குறியீடு', keyboard: 'number-pad', max: 10},
  {key: 'country_code', en: 'Country, 2 letters (IN, US…)', ta: 'நாடு, 2 எழுத்துகள் (IN, US…)', max: 2},
  {key: 'phone', en: 'Phone for delivery (optional)', ta: 'டெலிவரி தொலைபேசி (விருப்பம்)', keyboard: 'phone-pad', max: 16},
];

const oneLine = (a: Address) =>
  [a.full_name, a.line1, a.line2, a.city, a.state, a.postal_code, a.country_code].filter(Boolean).join(', ');

/** Where shop orders are delivered. Needed before checkout; PayPal shows it too. */
const AddressCard = ({token, tamil}: {token: string; tamil: boolean}) => {
  const [saved, setSaved] = useState<Address | null>(null);
  const [form, setForm] = useState<Address>(EMPTY);
  const [editing, setEditing] = useState(false);
  const [message, setMessage] = useState('');
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const data = await api('/api/shop/address', token);
      setSaved(data.address);
      setEditing(!data.address);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Could not load your address.');
    }
  }, [token]);

  useEffect(() => {
    load();
  }, [load]);

  const save = async () => {
    setBusy(true);
    setMessage('');
    try {
      const body = Object.fromEntries(
        Object.entries(form).map(([k, v]) => [k, typeof v === 'string' && v.trim() ? v.trim() : null]),
      );
      const data = await api('/api/shop/address', token, {method: 'PUT', body});
      setSaved(data.address);
      setEditing(false);
      playSound('request_sent');
      setMessage(t(tamil, 'Delivery address saved.', 'டெலிவரி முகவரி சேமிக்கப்பட்டது.'));
    } catch (error) {
      playSound('failed');
      setMessage(error instanceof Error ? error.message : 'Could not save the address.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <View style={ui.card}>
      <Text style={ui.heading} accessibilityRole="header">
        {t(tamil, 'Delivery address', 'டெலிவரி முகவரி')}
      </Text>
      {saved && !editing ? (
        <>
          <Text style={ui.body} accessible>
            {oneLine(saved)}
          </Text>
          <TouchableOpacity
            onPress={() => {
              setForm({...EMPTY, ...Object.fromEntries(Object.entries(saved).map(([k, v]) => [k, v ?? '']))});
              setEditing(true);
            }}
            accessibilityRole="button"
            accessibilityLabel={t(tamil, 'Change delivery address', 'டெலிவரி முகவரியை மாற்று')}
            style={ui.secondaryButton}>
            <Text style={ui.secondaryButtonText}>{t(tamil, 'Change address', 'முகவரியை மாற்று')}</Text>
          </TouchableOpacity>
        </>
      ) : (
        <>
          <Text style={ui.muted}>
            {t(tamil, 'Needed before you pay. PayPal shows it on the payment page.',
              'பணம் செலுத்தும் முன் தேவை. PayPal பக்கத்திலும் காட்டப்படும்.')}
          </Text>
          {FIELDS.map(field => (
            <View key={field.key}>
              <Text style={ui.label} nativeID={`addr_${field.key}`}>
                {t(tamil, field.en, field.ta)}
              </Text>
              <TextInput
                value={String(form[field.key] ?? '')}
                onChangeText={value =>
                  setForm(current => ({
                    ...current,
                    [field.key]: field.key === 'country_code' ? value.toUpperCase() : value,
                  }))
                }
                accessibilityLabelledBy={`addr_${field.key}`}
                keyboardType={field.keyboard ?? 'default'}
                autoCapitalize={field.key === 'country_code' ? 'characters' : 'words'}
                maxLength={field.max}
                style={ui.input}
              />
            </View>
          ))}
          <TouchableOpacity
            onPress={save}
            disabled={busy}
            accessibilityRole="button"
            accessibilityState={{disabled: busy, busy}}
            style={[ui.primaryButton, busy && ui.disabled]}>
            <Text style={ui.primaryButtonText}>{t(tamil, 'Save address', 'முகவரியைச் சேமி')}</Text>
          </TouchableOpacity>
          {saved && (
            <TouchableOpacity onPress={() => setEditing(false)} accessibilityRole="button" style={ui.secondaryButton}>
              <Text style={ui.secondaryButtonText}>{t(tamil, 'Cancel', 'ரத்து')}</Text>
            </TouchableOpacity>
          )}
        </>
      )}
      {message ? (
        <Text style={ui.body} accessibilityLiveRegion="polite">
          {message}
        </Text>
      ) : null}
    </View>
  );
};

export default AddressCard;
