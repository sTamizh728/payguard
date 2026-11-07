import React, {useCallback, useEffect, useState} from 'react';
import {AppState, Linking, StyleSheet, Text, TextInput, TouchableOpacity, View} from 'react-native';

import {api, PendingAction} from '../api';
import ConfirmBox from '../components/ConfirmBox';
import Segments from '../components/Segments';
import AddressCard from '../components/AddressCard';
import BestProducts from '../components/BestProducts';
import {playSound} from '../native';
import {confirmWithSecurity, Session, t} from '../session';
import {colors, ui} from '../theme';

type Result = {id: number; title: string; brand?: string; price: string; rating: number; stock: number};
type Review = {name: string; rating: number; comment: string};
type Details = Result & {description: string; shipping?: string; returns?: string; reviews: Review[]};
type CartItem = {product_id: number; title: string; price: string; quantity: number; line_total: string};
type Order = {
  code: string;
  name: string;
  name_ta: string;
  total: string;
  status: string;
  channel: string;
  approval_url: string | null;
  created_at: string;
  items: {title: string; price: string; quantity: number}[];
  delivery_by: string | null;
  paid_at: string | null;
  transaction_id: string | null;
};

const longDate = (iso: string | null) =>
  iso
    ? new Date(iso).toLocaleDateString('en-GB', {
        weekday: 'short',
        day: '2-digit',
        month: 'short',
        year: 'numeric',
      })
    : '—';

const stars = (rating: number) => `★ ${rating.toFixed(1)}`;

const ShopScreen = ({session}: {session: Session}) => {
  const {account, tamil} = session;
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<Result[]>([]);
  const [details, setDetails] = useState<Details | null>(null);
  const [quantity, setQuantity] = useState(1);
  const [cart, setCart] = useState<{items: CartItem[]; total: string}>({items: [], total: '0.00'});
  const [orders, setOrders] = useState<Order[]>([]);
  const [phoneNumber, setPhoneNumber] = useState<string | null>(null);
  const [code, setCode] = useState('');
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');
  const [openReceipt, setOpenReceipt] = useState<string | null>(null);
  // Pay with the saved PayPal: PIN + fingerprint, no PayPal page.
  const [pending, setPending] = useState<PendingAction | null>(null);
  const [part, setPart] = useState<'best' | 'shop' | 'cart' | 'orders'>('best');

  const run = async (work: () => Promise<void>) => {
    setBusy(true);
    setMessage('');
    try {
      await work();
    } catch (error) {
      setMessage(session.handleError(error));
      playSound('failed');
    } finally {
      setBusy(false);
    }
  };

  const load = useCallback(async () => {
    if (!account) {
      return;
    }
    try {
      const [c, o, p] = await Promise.all([
        api('/api/shop/cart', account.token),
        api('/api/shop/orders', account.token),
        api('/api/shop/products', account.token),
      ]);
      setCart(c);
      setOrders(o.orders);
      setPhoneNumber(p.phone_orders ? p.phone_number : null);
    } catch (error) {
      setMessage(session.handleError(error));
    }
  }, [account, session]);

  // Coming back from PayPal checkout: refresh, so a paid order shows as paid.
  useEffect(() => {
    load();
    const sub = AppState.addEventListener('change', state => state === 'active' && load());
    return () => sub.remove();
  }, [load]);

  if (!account) {
    return (
      <View style={ui.card}>
        <Text style={ui.body}>{t(tamil, 'Please log in on the Home tab first.', 'முதலில் முகப்பில் உள்நுழையுங்கள்.')}</Text>
      </View>
    );
  }

  const search = () =>
    run(async () => {
      const data = await api(`/api/shop/search?q=${encodeURIComponent(query.trim())}`, account.token);
      setResults(data.results);
      setDetails(null);
      setMessage(
        data.results.length
          ? t(tamil, `${data.results.length} products found.`, `${data.results.length} பொருட்கள் கிடைத்தன.`)
          : t(tamil, 'Nothing found. Try other words.', 'எதுவும் கிடைக்கவில்லை. வேறு சொற்களை முயலுங்கள்.'),
      );
    });

  const open = (id: number) =>
    run(async () => {
      setDetails(await api(`/api/shop/products/${id}`, account.token));
      setQuantity(1);
    });

  const setInCart = (productId: number, count: number) =>
    run(async () => {
      setCart(await api('/api/shop/cart', account.token, {body: {product_id: productId, quantity: count}}));
    });

  const addToCart = () =>
    run(async () => {
      if (!details) {
        return;
      }
      const already = cart.items.find(i => i.product_id === details.id)?.quantity ?? 0;
      setCart(await api('/api/shop/cart', account.token, {
        body: {product_id: details.id, quantity: already + quantity},
      }));
      playSound('request_sent');
      setMessage(t(tamil, `Added ${quantity} to your cart.`, `${quantity} கூடையில் சேர்க்கப்பட்டது.`));
    });

  const openCheckout = async (url: string) => {
    playSound('request_sent');
    await Linking.openURL(url);
  };

  const checkout = () =>
    run(async () => {
      const started = await api('/api/shop/pay', account.token, {body: {}});
      const action: PendingAction | null = started.pending_action;
      setMessage(started.reply);
      if (action?.type === 'checkout' && action.url) {
        // First time: PayPal's page (it can save PayPal for next time).
        setCart({items: [], total: '0.00'});
        await openCheckout(action.url);
        load();
      } else if (action) {
        setPending(action);
        playSound('confirm_needed');
      }
    });

  const confirmPay = (pin: string) =>
    run(async () => {
      if (!pending) {
        return;
      }
      try {
        const reply = await confirmWithSecurity(account.token, pending, pin);
        setPending(reply.pending_action);
        setMessage(reply.reply);
        if (reply.event === 'payment_sent') {
          setCart({items: [], total: '0.00'});
          load();
        }
      } catch (error) {
        const text = error instanceof Error && error.message ? error.message : 'Not confirmed.';
        setMessage(`${text} ${t(tamil, 'Nothing was paid.', 'எதுவும் செலுத்தப்படவில்லை.')}`);
      }
    });

  const claim = () =>
    run(async () => {
      const order = await api('/api/shop/claim', account.token, {body: {code: code.trim()}});
      setCode('');
      await openCheckout(order.approval_url);
      load();
    });

  return (
    <View>
      <Segments
        value={part}
        onChange={setPart}
        items={[
          {key: 'best', label: t(tamil, 'Best picks', 'சிறந்தவை')},
          {key: 'shop', label: t(tamil, 'Shop', 'கடை')},
          {key: 'cart', label: `${t(tamil, 'Cart', 'கூடை')}${cart.items.length ? ` (${cart.items.length})` : ''}`},
          {key: 'orders', label: t(tamil, 'Orders', 'ஆர்டர்கள்')},
        ]}
      />

      {/* ---- best-rated products on the web: bought on the store's own site ---- */}
      {part === 'best' && <BestProducts token={account.token} tamil={tamil} />}

      {/* ---- search ---- */}
      {part === 'shop' && (
      <View style={ui.card}>
        <Text style={ui.title} accessibilityRole="header">
          {t(tamil, 'PayGuard Shop', 'PayGuard கடை')}
        </Text>
        <Text style={ui.label} nativeID="searchLabel">
          {t(tamil, 'Search products', 'பொருட்களைத் தேடு')}
        </Text>
        <View style={styles.row}>
          <TextInput
            value={query}
            onChangeText={setQuery}
            onSubmitEditing={() => query.trim() && search()}
            accessibilityLabelledBy="searchLabel"
            returnKeyType="search"
            maxLength={60}
            style={[ui.input, styles.flex]}
          />
          <TouchableOpacity
            onPress={search}
            disabled={busy || !query.trim()}
            accessibilityRole="button"
            accessibilityLabel={t(tamil, 'Search', 'தேடு')}
            style={[styles.iconButton, (busy || !query.trim()) && ui.disabled]}>
            <Text style={styles.iconText}>{t(tamil, 'Search', 'தேடு')}</Text>
          </TouchableOpacity>
        </View>
        {message ? (
          <Text style={[ui.body, styles.gap]} accessibilityLiveRegion="polite">
            {message}
          </Text>
        ) : null}

        {results.map(r => (
          <TouchableOpacity
            key={r.id}
            onPress={() => open(r.id)}
            accessibilityRole="button"
            accessibilityLabel={`${r.title}, ${r.price} dollars, rated ${r.rating.toFixed(1)} out of 5. Open details`}
            style={[styles.result, details?.id === r.id && styles.selected]}>
            <Text style={styles.title}>{r.title}</Text>
            <Text style={ui.muted}>
              ${r.price} · {stars(r.rating)} · {r.stock > 0 ? t(tamil, 'in stock', 'கையிருப்பில்') : t(tamil, 'out of stock', 'இருப்பு இல்லை')}
            </Text>
          </TouchableOpacity>
        ))}
      </View>

      )}

      {/* ---- details + reviews ---- */}
      {part === 'shop' && details && (
        <View style={ui.card}>
          <Text style={ui.title} accessibilityRole="header">{details.title}</Text>
          <Text style={styles.price}>
            ${details.price} · {stars(details.rating)}
          </Text>
          <Text style={[ui.body, styles.gap]}>{details.description}</Text>
          <Text style={[ui.muted, styles.gap]}>
            {[details.shipping, details.returns, `${details.stock} ${t(tamil, 'in stock', 'கையிருப்பில்')}`]
              .filter(Boolean)
              .join(' · ')}
          </Text>

          <Text style={[ui.heading, styles.gap]} accessibilityRole="header">
            {t(tamil, 'Reviews', 'மதிப்புரைகள்')}
          </Text>
          {details.reviews.length === 0 && <Text style={ui.muted}>{t(tamil, 'No reviews yet.', 'இன்னும் மதிப்புரை இல்லை.')}</Text>}
          {details.reviews.map((rv, i) => (
            <View key={i} style={styles.review} accessible>
              <Text style={styles.reviewHead}>
                {rv.name} · {'★'.repeat(rv.rating)}{'☆'.repeat(Math.max(0, 5 - rv.rating))}
              </Text>
              <Text style={ui.body}>{rv.comment}</Text>
            </View>
          ))}

          <View style={[styles.row, styles.gap]}>
            <Text style={ui.label}>{t(tamil, 'Quantity', 'எண்ணிக்கை')}</Text>
            <TouchableOpacity
              onPress={() => setQuantity(Math.max(1, quantity - 1))}
              accessibilityRole="button"
              accessibilityLabel={t(tamil, 'One less', 'ஒன்று குறை')}
              style={styles.step}>
              <Text style={styles.stepText}>−</Text>
            </TouchableOpacity>
            <Text style={styles.quantity} accessibilityLiveRegion="polite"
              accessibilityLabel={`${t(tamil, 'Quantity', 'எண்ணிக்கை')} ${quantity}`}>
              {quantity}
            </Text>
            <TouchableOpacity
              onPress={() => setQuantity(Math.min(10, quantity + 1))}
              accessibilityRole="button"
              accessibilityLabel={t(tamil, 'One more', 'ஒன்று கூட்டு')}
              style={styles.step}>
              <Text style={styles.stepText}>+</Text>
            </TouchableOpacity>
          </View>
          <TouchableOpacity
            onPress={addToCart}
            disabled={busy || details.stock < 1}
            accessibilityRole="button"
            accessibilityState={{disabled: busy || details.stock < 1}}
            style={[ui.primaryButton, (busy || details.stock < 1) && ui.disabled]}>
            <Text style={ui.primaryButtonText}>{t(tamil, 'Add to cart', 'கூடையில் சேர்')}</Text>
          </TouchableOpacity>
        </View>
      )}

      {part === 'cart' && <AddressCard token={account.token} tamil={tamil} />}

      {part === 'cart' && pending && (
        <ConfirmBox
          action={pending}
          busy={busy}
          onConfirm={confirmPay}
          onCancel={() => {
            setPending(null);
            setMessage(t(tamil, 'Cancelled. Nothing was paid.', 'ரத்து. எதுவும் செலுத்தப்படவில்லை.'));
            api('/api/chat/cancel', account.token, {body: {}}).catch(() => {});
          }}
        />
      )}

      {/* ---- cart ---- */}
      {part === 'cart' && (
      <View style={ui.card}>
        <Text style={ui.heading} accessibilityRole="header">
          {t(tamil, 'Your cart', 'உங்கள் கூடை')}
        </Text>
        {cart.items.length === 0 && <Text style={ui.muted}>{t(tamil, 'Your cart is empty.', 'கூடை காலியாக உள்ளது.')}</Text>}
        {cart.items.map(item => (
          <View key={item.product_id} style={styles.cartRow}>
            <View style={styles.flex} accessible>
              <Text style={styles.title}>{item.title}</Text>
              <Text style={ui.muted}>
                {item.quantity} × ${item.price} = ${item.line_total}
              </Text>
            </View>
            <TouchableOpacity
              onPress={() => setInCart(item.product_id, item.quantity - 1)}
              accessibilityRole="button"
              accessibilityLabel={`${t(tamil, 'One less', 'ஒன்று குறை')} ${item.title}`}
              style={styles.step}>
              <Text style={styles.stepText}>−</Text>
            </TouchableOpacity>
            <TouchableOpacity
              onPress={() => setInCart(item.product_id, Math.min(10, item.quantity + 1))}
              accessibilityRole="button"
              accessibilityLabel={`${t(tamil, 'One more', 'ஒன்று கூட்டு')} ${item.title}`}
              style={styles.step}>
              <Text style={styles.stepText}>+</Text>
            </TouchableOpacity>
          </View>
        ))}
        {cart.items.length > 0 && (
          <TouchableOpacity
            onPress={checkout}
            disabled={busy}
            accessibilityRole="button"
            accessibilityState={{disabled: busy, busy}}
            style={[styles.payButton, busy && ui.disabled]}>
            <Text style={styles.payText}>
              {t(tamil, `Pay $${cart.total} with PayPal`, `PayPal மூலம் $${cart.total} செலுத்து`)}
            </Text>
          </TouchableOpacity>
        )}
      </View>

      )}

      {/* ---- phone orders (only when a Twilio number is set up) ---- */}
      {part === 'orders' && phoneNumber && (
        <View style={ui.card}>
          <Text style={ui.heading} accessibilityRole="header" nativeID="claimLabel">
            {t(tamil, 'Claim phone order', 'தொலைபேசி ஆர்டரைப் பெறு')}
          </Text>
          <Text style={ui.muted}>
            {t(tamil, `Order by calling ${phoneNumber}, then enter the 6-digit code you heard.`,
              `${phoneNumber} அழைத்து ஆர்டர் செய்து, கேட்ட 6 இலக்க எண்ணை உள்ளிடுங்கள்.`)}
          </Text>
          <TextInput
            value={code}
            onChangeText={value => setCode(value.replace(/\D/g, '').slice(0, 6))}
            accessibilityLabelledBy="claimLabel"
            keyboardType="number-pad"
            maxLength={6}
            style={[ui.input, styles.codeInput]}
          />
          <TouchableOpacity
            onPress={claim}
            disabled={busy || code.length !== 6}
            accessibilityRole="button"
            accessibilityState={{disabled: busy || code.length !== 6}}
            style={[ui.primaryButton, (busy || code.length !== 6) && ui.disabled]}>
            <Text style={ui.primaryButtonText}>{t(tamil, 'Open and pay', 'திறந்து செலுத்து')}</Text>
          </TouchableOpacity>
        </View>
      )}

      {/* ---- orders ---- */}
      {part === 'orders' && (
      <View style={ui.card}>
        <Text style={ui.heading} accessibilityRole="header">
          {t(tamil, 'My orders', 'என் ஆர்டர்கள்')}
        </Text>
        {orders.length === 0 && <Text style={ui.muted}>{t(tamil, 'No orders yet.', 'இன்னும் ஆர்டர் இல்லை.')}</Text>}
        {orders.map(order => (
          <View key={order.code} style={styles.order}>
            <Text style={styles.title}>{tamil ? order.name_ta : order.name}</Text>
            <Text style={[ui.muted, order.status === 'PAID' && styles.paid]}>
              ${order.total} ·{' '}
              {order.status === 'PAID'
                ? t(tamil, 'Paid', 'செலுத்தப்பட்டது')
                : t(tamil, 'Waiting for payment', 'செலுத்தக் காத்திருக்கிறது')}
              {order.channel === 'phone' ? ` · ${t(tamil, 'phone order', 'தொலைபேசி ஆர்டர்')}` : ''}
            </Text>
            {order.status === 'PAID' && order.delivery_by && (
              <Text style={ui.body}>
                {t(tamil, 'Expected delivery by', 'எதிர்பார்க்கும் டெலிவரி')} {longDate(order.delivery_by)}
              </Text>
            )}
            {order.approval_url && (
              <TouchableOpacity
                onPress={() => openCheckout(order.approval_url as string)}
                accessibilityRole="button"
                style={ui.secondaryButton}>
                <Text style={ui.secondaryButtonText}>{t(tamil, 'Pay now', 'இப்போது செலுத்து')}</Text>
              </TouchableOpacity>
            )}
            {order.status === 'PAID' && (
              <TouchableOpacity
                onPress={() => setOpenReceipt(openReceipt === order.code ? null : order.code)}
                accessibilityRole="button"
                accessibilityState={{expanded: openReceipt === order.code}}
                style={ui.secondaryButton}>
                <Text style={ui.secondaryButtonText}>
                  {openReceipt === order.code
                    ? t(tamil, 'Hide receipt', 'ரசீதை மறை')
                    : t(tamil, 'View receipt', 'ரசீதைப் பார்')}
                </Text>
              </TouchableOpacity>
            )}
            {openReceipt === order.code && (
              <View style={styles.receipt} accessibilityLiveRegion="polite">
                <Text style={ui.heading} accessibilityRole="header">
                  {t(tamil, 'Receipt', 'ரசீது')} · {t(tamil, 'Order', 'ஆர்டர்')} {order.code}
                </Text>
                {order.items.map((item, i) => (
                  <Text key={i} style={ui.body}>
                    {item.quantity} × {item.title} @ ${item.price} = $
                    {(Number(item.price) * item.quantity).toFixed(2)}
                  </Text>
                ))}
                <Text style={[styles.title, styles.receiptTotal]}>
                  {t(tamil, 'Total paid', 'மொத்தம் செலுத்தியது')}: ${order.total} USD
                </Text>
                <Text style={ui.muted}>
                  {t(tamil, 'Paid on', 'செலுத்திய நாள்')}: {longDate(order.paid_at)}
                </Text>
                <Text style={ui.muted}>{t(tamil, 'Paid with', 'செலுத்திய முறை')}: PayPal</Text>
                <Text style={ui.muted} selectable>
                  {t(tamil, 'PayPal transaction', 'PayPal பரிவர்த்தனை')}: {order.transaction_id ?? '—'}
                </Text>
                <Text style={ui.muted}>
                  {t(tamil, 'Expected delivery by', 'எதிர்பார்க்கும் டெலிவரி')}: {longDate(order.delivery_by)}
                </Text>
                <Text style={ui.muted}>
                  {t(tamil, 'Sold by PayGuard Shop (sandbox demo)', 'விற்பனையாளர்: PayGuard கடை (சோதனை)')}
                </Text>
              </View>
            )}
          </View>
        ))}
      </View>
      )}
    </View>
  );
};

const styles = StyleSheet.create({
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 10,
  },
  flex: {
    flex: 1,
  },
  gap: {
    marginTop: 10,
  },
  iconButton: {
    minHeight: 48,
    paddingHorizontal: 16,
    borderRadius: 12,
    backgroundColor: colors.brand,
    alignItems: 'center',
    justifyContent: 'center',
  },
  iconText: {
    color: '#FFFFFF',
    fontSize: 16,
    fontWeight: '700',
  },
  result: {
    borderWidth: 1,
    borderColor: colors.line,
    borderRadius: 12,
    padding: 14,
    marginTop: 10,
  },
  selected: {
    borderColor: colors.brand,
    borderWidth: 2,
    backgroundColor: colors.brandSoft,
  },
  title: {
    color: colors.ink,
    fontSize: 17,
    fontWeight: '700',
  },
  price: {
    color: colors.ink,
    fontSize: 18,
    fontWeight: '800',
  },
  review: {
    backgroundColor: '#F8FAFC',
    borderRadius: 10,
    padding: 12,
    marginBottom: 8,
  },
  reviewHead: {
    color: colors.muted,
    fontSize: 14,
    fontWeight: '700',
    marginBottom: 4,
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
  cartRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    paddingVertical: 8,
    borderBottomWidth: 1,
    borderBottomColor: '#E2E8F0',
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
  receipt: {
    borderWidth: 1,
    borderColor: colors.line,
    borderStyle: 'dashed',
    borderRadius: 10,
    padding: 14,
    marginTop: 10,
    backgroundColor: colors.card,
  },
  receiptTotal: {
    marginTop: 8,
    marginBottom: 6,
  },
});

export default ShopScreen;
