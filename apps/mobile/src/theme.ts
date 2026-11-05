import {StyleSheet} from 'react-native';

export const colors = {
  page: '#F3F6FC',
  card: '#FFFFFF',
  ink: '#101827',
  muted: '#475569',
  line: '#B8C4D6',
  navy: '#101827',
  brandBlue: '#2563EB',
  paypalYellow: '#FFC439',
  paypalNavy: '#003087',
  good: '#166534',
  goodBg: '#ECFDF3',
  warn: '#B45309',
  warnBg: '#FFFBEB',
  bad: '#B42318',
  badBg: '#FEF3F2',
};

export const ui = StyleSheet.create({
  card: {
    backgroundColor: colors.card,
    borderRadius: 16,
    padding: 18,
    marginBottom: 16,
  },
  title: {
    color: colors.ink,
    fontSize: 22,
    fontWeight: '800',
    marginBottom: 12,
  },
  heading: {
    color: colors.ink,
    fontSize: 17,
    fontWeight: '700',
    marginBottom: 10,
  },
  body: {
    color: colors.ink,
    fontSize: 16,
    lineHeight: 24,
  },
  muted: {
    color: colors.muted,
    fontSize: 14,
    lineHeight: 21,
  },
  error: {
    color: colors.bad,
    fontSize: 15,
    marginTop: 10,
  },
  label: {
    color: colors.ink,
    fontSize: 15,
    fontWeight: '600',
    marginBottom: 6,
    marginTop: 10,
  },
  input: {
    borderWidth: 1,
    borderColor: colors.line,
    borderRadius: 10,
    paddingHorizontal: 12,
    paddingVertical: 11,
    fontSize: 17,
    color: colors.ink,
    backgroundColor: colors.card,
  },
  primaryButton: {
    backgroundColor: colors.navy,
    paddingVertical: 15,
    paddingHorizontal: 16,
    borderRadius: 12,
    alignItems: 'center',
    marginTop: 14,
  },
  primaryButtonText: {
    color: '#FFFFFF',
    fontSize: 17,
    fontWeight: '700',
  },
  secondaryButton: {
    backgroundColor: colors.card,
    borderWidth: 1,
    borderColor: colors.line,
    paddingVertical: 13,
    paddingHorizontal: 16,
    borderRadius: 12,
    alignItems: 'center',
    marginTop: 12,
  },
  secondaryButtonText: {
    color: colors.ink,
    fontSize: 16,
    fontWeight: '600',
  },
  disabled: {
    opacity: 0.5,
  },
});
