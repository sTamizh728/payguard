import React from 'react';
import {StyleSheet, Text, TouchableOpacity, View} from 'react-native';

import {PendingAction} from '../api';
import {colors} from '../theme';

type Props = {
  action: PendingAction;
  busy: boolean;
  onConfirm: () => void;
  onCancel: () => void;
};

/** The only place money can move: fingerprint / face / PIN, then the server checks it. */
const ConfirmBox = ({action, busy, onConfirm, onCancel}: Props) => (
  <View style={styles.box} accessibilityLiveRegion="polite">
    <Text style={styles.text} accessibilityRole="header">
      {action.summary}?
    </Text>
    <Text style={styles.hint}>
      Confirm with your fingerprint, face or phone PIN.
    </Text>
    <View style={styles.row}>
      <TouchableOpacity
        onPress={onConfirm}
        disabled={busy}
        accessibilityRole="button"
        accessibilityLabel={`Confirm with fingerprint or PIN: ${action.summary}`}
        accessibilityState={{disabled: busy, busy}}
        style={[styles.button, styles.yes, busy && styles.disabled]}>
        <Text style={styles.yesText}>{busy ? 'Please wait...' : '🔒 Confirm'}</Text>
      </TouchableOpacity>
      <TouchableOpacity
        onPress={onCancel}
        disabled={busy}
        accessibilityRole="button"
        accessibilityState={{disabled: busy}}
        style={[styles.button, styles.no]}>
        <Text style={styles.noText}>Cancel</Text>
      </TouchableOpacity>
    </View>
  </View>
);

const styles = StyleSheet.create({
  box: {
    borderWidth: 2,
    borderColor: '#F59E0B',
    backgroundColor: colors.warnBg,
    borderRadius: 14,
    padding: 16,
    marginVertical: 10,
  },
  text: {
    color: colors.ink,
    fontSize: 18,
    fontWeight: '800',
  },
  hint: {
    color: colors.muted,
    fontSize: 14,
    marginTop: 4,
    marginBottom: 12,
  },
  row: {
    flexDirection: 'row',
    gap: 10,
  },
  button: {
    flex: 1,
    paddingVertical: 15,
    borderRadius: 12,
    alignItems: 'center',
  },
  yes: {
    backgroundColor: colors.good,
  },
  yesText: {
    color: '#FFFFFF',
    fontSize: 17,
    fontWeight: '800',
  },
  no: {
    backgroundColor: colors.card,
    borderWidth: 1,
    borderColor: colors.line,
  },
  noText: {
    color: colors.ink,
    fontSize: 17,
    fontWeight: '700',
  },
  disabled: {
    opacity: 0.6,
  },
});

export default ConfirmBox;
