import React from 'react';
import {StyleSheet, Text, TouchableOpacity, View} from 'react-native';

import {colors, TOUCH} from '../theme';

type Props<T extends string> = {
  items: {key: T; label: string}[];
  value: T;
  onChange: (key: T) => void;
};

/** A row of tabs inside a screen (Track, Shop): one part of a long screen at a time. */
function Segments<T extends string>({items, value, onChange}: Props<T>) {
  return (
    <View style={styles.row} accessibilityRole="tablist">
      {items.map((item, index) => {
        const selected = item.key === value;
        return (
          <TouchableOpacity
            key={item.key}
            onPress={() => onChange(item.key)}
            accessibilityRole="tab"
            accessibilityState={{selected}}
            accessibilityLabel={`${item.label}, ${index + 1} of ${items.length}`}
            style={[styles.item, selected && styles.itemOn]}>
            <Text
              style={[styles.text, selected && styles.textOn]}
              numberOfLines={1}
              adjustsFontSizeToFit
              maxFontSizeMultiplier={1.5}>
              {item.label}
            </Text>
          </TouchableOpacity>
        );
      })}
    </View>
  );
}

const styles = StyleSheet.create({
  row: {
    flexDirection: 'row',
    backgroundColor: '#EAE5DA',
    borderRadius: 12,
    padding: 3,
    marginBottom: 16,
  },
  item: {
    flex: 1,
    minHeight: TOUCH - 4,
    borderRadius: 9,
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: 4,
  },
  itemOn: {
    backgroundColor: colors.card,
    borderWidth: 1,
    borderColor: colors.edge,
  },
  text: {
    color: colors.muted,
    fontSize: 14,
    fontWeight: '600',
  },
  textOn: {
    color: colors.ink,
    fontWeight: '800',
  },
});

export default Segments;
