import React from 'react';
import {Text, TextInput} from 'react-native';

import {ui} from '../theme';

type Props = {
  label: string;
  value: string;
  onChange: (pin: string) => void;
  onDone?: () => void;
  autoFocus?: boolean;
};

/** A 4-6 digit PayGuard PIN: number keypad, hidden digits, a clear spoken label. */
const PinField = ({label, value, onChange, onDone, autoFocus}: Props) => (
  <>
    <Text style={ui.label} importantForAccessibility="no">
      {label}
    </Text>
    <TextInput
      value={value}
      onChangeText={text => onChange(text.replace(/\D/g, '').slice(0, 6))}
      onSubmitEditing={onDone}
      keyboardType="number-pad"
      secureTextEntry
      maxLength={6}
      autoFocus={autoFocus}
      autoComplete="off"
      importantForAutofill="no"
      accessibilityLabel={`${label}, 4 to 6 digits`}
      style={[ui.input, {letterSpacing: 8, fontSize: 22}]}
    />
  </>
);

export default PinField;
