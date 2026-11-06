import React, { useCallback, useEffect, useState } from 'react';
import {
  AppState,
  Linking,
  StyleSheet,
  Text,
  TextInput,
  TouchableOpacity,
  View,
} from 'react-native';

import { api } from '../api';
import { playSound } from '../native';
import { Session, t } from '../session';
import { colors, ui } from '../theme';

type Product = { id: string; name: string; price: string };
type Order = {
  code: string;
  name: string;
  name_ta: string;
  quantity: number;
  total: string;
  status: string;
  channel: string;
  approval_url: string | null;
};

const ShopScreen = ({ session }: { session: Session }) => {
  const { account, tamil } = session;
  const [products, setProducts] = useState<Product[]>([]);
  const [chosen, setChosen] = useState<Product | null>(null);
  const [quantity, setQuantity] = useState(1);
  const [orders, setOrders] = useState<Order[]>([]);
  const [code, setCode] = useState('');
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');
  // Phone ordering shows only when the server has a Twilio number.
  const [phoneNumber, setPhoneNumber] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!account) {
      return;
    }
    try {
      const [p, o] = await Promise.all([
        api('/api/shop/products', account.token),
        api('/api/shop/orders', account.token),
      ]);
      setProducts(p.products);
      setPhoneNumber(p.phone_orders ? p.phone_number : null);
      setOrders(o.orders);
    } catch (error) {
      setMessage(session.handleError(error));
    }
  }, [account, session]);

  // Coming back from PayPal checkout: refresh, so a paid order shows as paid.
  useEffect(() => {
    load();
    const sub = AppState.addEventListener(
      'change',
      state => state === 'active' && load(),
    );
    return () => sub.remove();
  }, [load]);

  if (!account) {
    return (
      <View style={ui.card}>
        <Text style={ui.body}>
          {t(
            tamil,
            'Please log in on the Home tab first.',
            'முதலில் முகப்பில் உள்நுழையுங்கள்.',
          )}
        </Text>
      </View>
    );
  }

  const openCheckout = async (url: string) => {
    playSound('request_sent');
    await Linking.openURL(url);
  };

  const buy = async () => {
    if (!chosen) {
      setMessage(
        t(
          tamil,
          'Choose a product first.',
          'முதலில் ஒரு பொருளைத் தேர்ந்தெடுங்கள்.',
        ),
      );
      return;
    }
    setBusy(true);
    setMessage('');
    try {
      const order = await api('/api/shop/orders', account.token, {
        body: { product_id: chosen.id, quantity },
      });
      setMessage(
        t(
          tamil,
          `Order ${order.code}: opening PayPal to pay $${order.total}.`,
          `ஆர்டர் ${order.code}: $${order.total} செலுத்த PayPal திறக்கிறது.`,
        ),
      );
      await openCheckout(order.approval_url);
      load();
    } catch (error) {
      setMessage(session.handleError(error));
      playSound('failed');
    } finally {
      setBusy(false);
    }
  };

  const claim = async () => {
    setBusy(true);
    setMessage('');
    try {
      const order = await api('/api/shop/claim', account.token, {
        body: { code: code.trim() },
      });
      setCode('');
      await openCheckout(order.approval_url);
      load();
    } catch (error) {
      setMessage(session.handleError(error));
      playSound('failed');
    } finally {
      setBusy(false);
    }
  };

  const total = chosen ? (Number(chosen.price) * quantity).toFixed(2) : '0.00';

  return (
    <View>
      <View style={ui.card}>
        <Text style={ui.title} accessibilityRole="header">
          {t(tamil, 'PayGuard Shop', 'PayGuard கடை')}
        </Text>
        <Text style={ui.muted}>
          {phoneNumber
            ? t(
                tamil,
                `Pay safely in PayPal checkout. You can also order by calling ${phoneNumber}.`,
                `PayPal-இல் பாதுகாப்பாகச் செலுத்துங்கள். ${phoneNumber} அழைத்தும் ஆர்டர் செய்யலாம்.`,
              )
            : t(
                tamil,
                'Pay safely in PayPal checkout.',
                'PayPal-இல் பாதுகாப்பாகச் செலுத்துங்கள்.',
              )}
        </Text>

        <View accessibilityRole="radiogroup" style={styles.list}>
          {products.map(product => {
            const selected = chosen?.id === product.id;
            return (
              <TouchableOpacity
                key={product.id}
                onPress={() => setChosen(product)}
                accessibilityRole="radio"
                accessibilityState={{ checked: selected }}
                accessibilityLabel={`${product.name}, ${product.price} dollars`}
                style={[styles.product, selected && styles.selected]}
              >
                <Text style={styles.radio}>{selected ? '◉' : '○'}</Text>
                <Text style={styles.productName}>{product.name}</Text>
                <Text style={styles.price}>${product.price}</Text>
              </TouchableOpacity>
            );
          })}
        </View>

        <View style={styles.quantityRow}>
          <Text style={ui.label}>{t(tamil, 'Quantity', 'எண்ணிக்கை')}</Text>
          <TouchableOpacity
            onPress={() => setQuantity(Math.max(1, quantity - 1))}
            accessibilityRole="button"
            accessibilityLabel={t(tamil, 'One less', 'ஒன்று குறை')}
            style={styles.step}
          >
            <Text style={styles.stepText}>−</Text>
          </TouchableOpacity>
          <Text
            style={styles.quantity}
            accessibilityLiveRegion="polite"
            accessibilityLabel={`${t(
              tamil,
              'Quantity',
              'எண்ணிக்கை',
            )} ${quantity}`}
          >
            {quantity}
          </Text>
          <TouchableOpacity
            onPress={() => setQuantity(Math.min(10, quantity + 1))}
            accessibilityRole="button"
            accessibilityLabel={t(tamil, 'One more', 'ஒன்று கூட்டு')}
            style={styles.step}
          >
            <Text style={styles.stepText}>+</Text>
          </TouchableOpacity>
        </View>

        <TouchableOpacity
          onPress={buy}
          disabled={busy}
          accessibilityRole="button"
          accessibilityState={{ disabled: busy, busy }}
          style={[styles.payButton, busy && ui.disabled]}
        >
          <Text style={styles.payText}>
            {t(
              tamil,
              `Pay $${total} with PayPal`,
              `PayPal மூலம் $${total} செலுத்து`,
            )}
          </Text>
        </TouchableOpacity>
        {message ? (
          <Text
            style={[ui.body, styles.message]}
            accessibilityLiveRegion="polite"
          >
            {message}
          </Text>
        ) : null}
      </View>

      {phoneNumber && (
        <View style={ui.card}>
          <Text
            style={ui.heading}
            accessibilityRole="header"
            nativeID="claimLabel"
          >
            {t(tamil, 'Claim phone order', 'தொலைபேசி ஆர்டரைப் பெறு')}
          </Text>
          <Text style={ui.muted}>
            {t(
              tamil,
              'Enter the 6-digit code you heard on the call.',
              'அழைப்பில் கேட்ட 6 இலக்க எண்ணை உள்ளிடுங்கள்.',
            )}
          </Text>
          <TextInput
            value={code}
            onChangeText={value =>
              setCode(value.replace(/\D/g, '').slice(0, 6))
            }
            accessibilityLabelledBy="claimLabel"
            keyboardType="number-pad"
            maxLength={6}
            style={[ui.input, styles.codeInput]}
          />
          <TouchableOpacity
            onPress={claim}
            disabled={busy || code.length !== 6}
            accessibilityRole="button"
            accessibilityState={{ disabled: busy || code.length !== 6 }}
            style={[
              ui.primaryButton,
              (busy || code.length !== 6) && ui.disabled,
            ]}
          >
            <Text style={ui.primaryButtonText}>
              {t(tamil, 'Open and pay', 'திறந்து செலுத்து')}
            </Text>
          </TouchableOpacity>
        </View>
      )}

      <View style={ui.card}>
        <Text style={ui.heading} accessibilityRole="header">
          {t(tamil, 'My orders', 'என் ஆர்டர்கள்')}
        </Text>
        {orders.length === 0 && (
          <Text style={ui.muted}>
            {t(tamil, 'No orders yet.', 'இன்னும் ஆர்டர் இல்லை.')}
          </Text>
        )}
        {orders.map(order => (
          <View
            key={order.code}
            style={styles.order}
            accessible={!order.approval_url}
          >
            <Text style={styles.productName}>
              {order.quantity} × {tamil ? order.name_ta : order.name} · $
              {order.total}
            </Text>
            <Text style={[ui.muted, order.status === 'PAID' && styles.paid]}>
              {order.status === 'PAID'
                ? t(tamil, '✅ Paid', '✅ செலுத்தப்பட்டது')
                : t(tamil, 'Waiting for payment', 'செலுத்தக் காத்திருக்கிறது')}
              {order.channel === 'phone'
                ? ` · ${t(tamil, 'phone order', 'தொலைபேசி ஆர்டர்')}`
                : ''}
              {` · ${order.code}`}
            </Text>
            {order.approval_url && (
              <TouchableOpacity
                onPress={() => openCheckout(order.approval_url as string)}
                accessibilityRole="button"
                style={ui.secondaryButton}
              >
                <Text style={ui.secondaryButtonText}>
                  {t(tamil, 'Pay now', 'இப்போது செலுத்து')}
                </Text>
              </TouchableOpacity>
            )}
          </View>
        ))}
      </View>
    </View>
  );
};

const styles = StyleSheet.create({
  list: {
    marginTop: 12,
  },
  product: {
    flexDirection: 'row',
    alignItems: 'center',
    borderWidth: 1,
    borderColor: colors.line,
    borderRadius: 12,
    padding: 14,
    marginBottom: 8,
  },
  selected: {
    borderColor: colors.brandBlue,
    borderWidth: 2,
    backgroundColor: '#E8F0FE',
  },
  radio: {
    fontSize: 22,
    marginRight: 12,
    color: colors.brandBlue,
  },
  productName: {
    flex: 1,
    color: colors.ink,
    fontSize: 17,
    fontWeight: '700',
  },
  price: {
    color: colors.ink,
    fontSize: 17,
    fontWeight: '800',
  },
  quantityRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
    marginTop: 4,
  },
  step: {
    width: 48,
    height: 48,
    borderRadius: 24,
    borderWidth: 1,
    borderColor: colors.line,
    alignItems: 'center',
    justifyContent: 'center',
  },
  stepText: {
    fontSize: 24,
    color: colors.ink,
  },
  quantity: {
    fontSize: 22,
    fontWeight: '800',
    color: colors.ink,
    minWidth: 28,
    textAlign: 'center',
  },
  payButton: {
    backgroundColor: colors.paypalYellow,
    paddingVertical: 16,
    borderRadius: 12,
    alignItems: 'center',
    marginTop: 16,
  },
  payText: {
    color: colors.paypalNavy,
    fontSize: 17,
    fontWeight: '800',
  },
  message: {
    marginTop: 12,
  },
  codeInput: {
    marginTop: 10,
    fontSize: 22,
    letterSpacing: 6,
  },
  order: {
    borderLeftWidth: 4,
    borderLeftColor: colors.line,
    backgroundColor: '#F8FAFC',
    borderRadius: 8,
    padding: 12,
    marginBottom: 8,
  },
  paid: {
    color: colors.good,
    fontWeight: '700',
  },
});

export default ShopScreen;
