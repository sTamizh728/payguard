import React from 'react';
import {StyleSheet, Text, View} from 'react-native';

import {colors} from '../theme';

/** PayGuard's mark: a rounded shield-green tile with "PG". Decoration only. */
const BrandMark = ({size = 36}: {size?: number}) => (
  <View
    importantForAccessibility="no-hide-descendants"
    accessibilityElementsHidden
    style={[styles.tile, {width: size, height: size, borderRadius: size * 0.28}]}>
    <Text style={[styles.text, {fontSize: size * 0.42}]} allowFontScaling={false}>
      PG
    </Text>
  </View>
);

const styles = StyleSheet.create({
  tile: {
    backgroundColor: colors.brand,
    alignItems: 'center',
    justifyContent: 'center',
    borderBottomRightRadius: 4,
  },
  text: {
    color: '#FFFFFF',
    fontWeight: '800',
    letterSpacing: -0.5,
  },
});

export default BrandMark;
