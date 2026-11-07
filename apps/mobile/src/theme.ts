import {StyleSheet} from 'react-native';

// PayGuard's look: warm paper background, deep ink text, one calm green for
// "safe" actions, and PayPal's own yellow only on PayPal buttons.
// Text colours meet WCAG AA (4.5:1) on both page and card backgrounds;
// borders that show where to tap meet 3:1.
export const colors = {
  page: '#F5F2EB',
  card: '#FFFFFF',
  sunk: '#FAF8F3', // rows inside a card
  ink: '#17202E',
  muted: '#4D5563',
  line: '#E2DCCF', // decoration only
  edge: '#857D6D', // input and button outlines (3:1)
  navy: '#17202E',
  brand: '#0D6B57', // PayGuard green: confirm, primary actions
  brandSoft: '#E3F1EC',
  brandBlue: '#1D4ED8', // links and selection
  paypalYellow: '#FFC439',
  paypalNavy: '#003087',
  good: '#166534',
  goodBg: '#EAF6EE',
  warn: '#8A4B08',
  warnBg: '#FDF4E3',
  bad: '#B42318',
  badBg: '#FDEEEC',
};

export const space = {xs: 4, s: 8, m: 12, l: 16, xl: 24};

// The smallest thing anyone has to tap (Android guideline: 48dp).
export const TOUCH = 48;

export const ui = StyleSheet.create({
  card: {
    backgroundColor: colors.card,
    borderRadius: 14,
    borderWidth: 1,
    borderColor: colors.line,
    padding: space.l,
    marginBottom: space.l,
  },
  title: {
    color: colors.ink,
    fontSize: 24,
    fontWeight: '700',
    letterSpacing: -0.3,
    marginBottom: space.s,
  },
  heading: {
    color: colors.ink,
    fontSize: 18,
    fontWeight: '700',
    marginBottom: space.s,
  },
  // Small caps label above a group of cards, like a section name in a bank app.
  section: {
    color: colors.muted,
    fontSize: 13,
    fontWeight: '700',
    letterSpacing: 0.8,
    textTransform: 'uppercase',
    marginBottom: space.s,
    marginTop: space.xs,
  },
  body: {
    color: colors.ink,
    fontSize: 16,
    lineHeight: 24,
  },
  muted: {
    color: colors.muted,
    fontSize: 15,
    lineHeight: 22,
  },
  error: {
    color: colors.bad,
    fontSize: 15,
    lineHeight: 22,
    marginTop: space.m,
  },
  label: {
    color: colors.ink,
    fontSize: 15,
    fontWeight: '600',
    marginBottom: 6,
    marginTop: space.m,
  },
  input: {
    borderWidth: 1.5,
    borderColor: colors.edge,
    borderRadius: 10,
    paddingHorizontal: space.m,
    paddingVertical: 10,
    minHeight: TOUCH,
    fontSize: 17,
    color: colors.ink,
    backgroundColor: colors.card,
  },
  primaryButton: {
    backgroundColor: colors.brand,
    minHeight: 52,
    paddingVertical: 14,
    paddingHorizontal: space.l,
    borderRadius: 12,
    alignItems: 'center',
    justifyContent: 'center',
    marginTop: space.m,
  },
  primaryButtonText: {
    color: '#FFFFFF',
    fontSize: 17,
    fontWeight: '700',
    textAlign: 'center',
  },
  secondaryButton: {
    backgroundColor: colors.card,
    borderWidth: 1.5,
    borderColor: colors.edge,
    minHeight: TOUCH,
    paddingVertical: 12,
    paddingHorizontal: space.l,
    borderRadius: 12,
    alignItems: 'center',
    justifyContent: 'center',
    marginTop: space.m,
  },
  secondaryButtonText: {
    color: colors.ink,
    fontSize: 16,
    fontWeight: '600',
    textAlign: 'center',
  },
  disabled: {
    opacity: 0.45,
  },
});
