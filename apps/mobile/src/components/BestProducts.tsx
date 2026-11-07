import React, {useState} from 'react';
import {Linking, StyleSheet, Text, TextInput, TouchableOpacity, View} from 'react-native';

import {api} from '../api';
import {playSound} from '../native';
import {t} from '../session';
import {colors, ui} from '../theme';

export type WebProduct = {
  rank: number;
  title: string;
  price: string;
  rating: number;
  reviews: number;
  store: string;
  link: string;
  delivery?: string | null;
};

export const WebProductRow = ({item, tamil}: {item: WebProduct; tamil: boolean}) => {
  const summary =
    `${item.rank}. ${item.title}. ${item.price ? `${item.price}, ` : ''}${item.store}. ` +
    `${t(tamil, 'Rated', 'மதிப்பீடு')} ${item.rating.toFixed(1)} ${t(tamil, 'out of 5', '/ 5')}` +
    (item.reviews ? `, ${item.reviews.toLocaleString()} ${t(tamil, 'reviews', 'மதிப்புரைகள்')}` : '');
  return (
    <View style={styles.item}>
      <View accessible accessibilityLabel={summary}>
        <Text style={styles.title}>{`${item.rank}. ${item.title}`}</Text>
        <Text style={styles.price}>{item.price}</Text>
        <Text style={ui.muted}>
          {`★ ${item.rating.toFixed(1)}${item.reviews ? ` (${item.reviews.toLocaleString()})` : ''} · ${item.store}`}
          {item.delivery ? ` · ${item.delivery}` : ''}
        </Text>
      </View>
      <TouchableOpacity
        onPress={() => Linking.openURL(item.link)}
        accessibilityRole="link"
        accessibilityLabel={t(tamil, `Open ${item.title} at ${item.store}`, `${item.store}-இல் ${item.title} திற`)}
        style={styles.open}>
        <Text style={styles.openText}>{t(tamil, `Open at ${item.store}`, `${item.store}-இல் திற`)} ↗</Text>
      </TouchableOpacity>
    </View>
  );
};

/** Top-rated products from Google Shopping. The person buys on the store's own site. */
const BestProducts = ({token, tamil}: {token: string; tamil: boolean}) => {
  const [query, setQuery] = useState('');
  const [items, setItems] = useState<WebProduct[]>([]);
  const [message, setMessage] = useState('');
  const [busy, setBusy] = useState(false);

  const find = async () => {
    if (query.trim().length < 2) {
      return;
    }
    setBusy(true);
    setMessage(t(tamil, 'Searching stores…', 'கடைகளில் தேடுகிறது…'));
    try {
      const data = await api(`/api/shop/web?q=${encodeURIComponent(query.trim())}`, token);
      setItems(data.results);
      setMessage(
        data.results.length
          ? t(tamil, `Top ${data.results.length} by rating and reviews.`, `மதிப்பீட்டின்படி முதல் ${data.results.length}.`)
          : t(tamil, 'No well-rated products found. Try other words.', 'நல்ல மதிப்பீடு உள்ள பொருட்கள் இல்லை.'),
      );
      playSound(data.results.length ? 'request_sent' : 'failed');
    } catch (error) {
      setItems([]);
      setMessage(error instanceof Error ? error.message : 'Search failed.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <View style={ui.card}>
      <Text style={ui.title} accessibilityRole="header">
        {t(tamil, 'Find the best products', 'சிறந்த பொருட்களைக் கண்டுபிடி')}
      </Text>
      <Text style={ui.muted}>
        {t(tamil, 'Top rated from online stores (Google Shopping). Open the store to buy there. Tip: add a budget, like "earbuds under 3000".',
          'ஆன்லைன் கடைகளில் சிறந்த மதிப்பீடு. வாங்க கடையைத் திறக்கவும். எ.கா. "earbuds under 3000".')}
      </Text>
      <Text style={ui.label} nativeID="bestLabel">
        {t(tamil, 'What are you looking for?', 'நீங்கள் எதைத் தேடுகிறீர்கள்?')}
      </Text>
      <View style={styles.row}>
        <TextInput
          value={query}
          onChangeText={setQuery}
          onSubmitEditing={find}
          accessibilityLabelledBy="bestLabel"
          returnKeyType="search"
          maxLength={100}
          style={[ui.input, styles.flex]}
        />
        <TouchableOpacity
          onPress={find}
          disabled={busy || query.trim().length < 2}
          accessibilityRole="button"
          accessibilityLabel={t(tamil, 'Find best products', 'சிறந்தவற்றைத் தேடு')}
          style={[styles.go, (busy || query.trim().length < 2) && ui.disabled]}>
          <Text style={styles.goText}>⭐</Text>
        </TouchableOpacity>
      </View>
      {message ? (
        <Text style={[ui.body, styles.gap]} accessibilityLiveRegion="polite">
          {message}
        </Text>
      ) : null}
      {items.map(item => (
        <WebProductRow key={`${item.rank}-${item.link}`} item={item} tamil={tamil} />
      ))}
    </View>
  );
};

const styles = StyleSheet.create({
  row: {flexDirection: 'row', gap: 8, alignItems: 'center'},
  flex: {flex: 1},
  gap: {marginTop: 10},
  go: {
    backgroundColor: colors.navy,
    borderRadius: 10,
    width: 52,
    height: 50,
    alignItems: 'center',
    justifyContent: 'center',
  },
  goText: {fontSize: 22},
  item: {
    borderWidth: 1,
    borderColor: colors.line,
    borderRadius: 12,
    padding: 12,
    marginTop: 10,
  },
  title: {color: colors.ink, fontSize: 16, fontWeight: '700'},
  price: {color: colors.good, fontSize: 18, fontWeight: '800', marginTop: 2},
  open: {
    marginTop: 10,
    backgroundColor: colors.paypalYellow,
    borderRadius: 10,
    paddingVertical: 12,
    alignItems: 'center',
  },
  openText: {color: colors.paypalNavy, fontSize: 16, fontWeight: '800'},
});

export default BestProducts;
