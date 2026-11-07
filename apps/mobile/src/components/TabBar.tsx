import React from 'react';
import {StyleSheet, Text, TouchableOpacity, View} from 'react-native';

import {colors, TOUCH} from '../theme';

export type TabName = 'home' | 'assistant' | 'shop' | 'send' | 'history' | 'profile';

type Props = {
  current: TabName;
  onChange: (tab: TabName) => void;
  tamil: boolean;
  // Height of Android's navigation buttons under the app.
  bottomInset?: number;
};

const TABS: {name: TabName; en: string; ta: string}[] = [
  {name: 'home', en: 'Home', ta: 'முகப்பு'},
  {name: 'assistant', en: 'Talk', ta: 'பேசு'},
  {name: 'shop', en: 'Shop', ta: 'கடை'},
  {name: 'send', en: 'Send', ta: 'அனுப்பு'},
  {name: 'history', en: 'Track', ta: 'கண்காணி'},
  {name: 'profile', en: 'Me', ta: 'நான்'},
];

/** Plain words, a bar over the chosen tab. Large fonts still fit on one line. */
const TabBar = ({current, onChange, tamil, bottomInset = 0}: Props) => (
  <View style={[styles.bar, {paddingBottom: 4 + bottomInset}]} accessibilityRole="tablist">
    {TABS.map((tab, index) => {
      const selected = tab.name === current;
      const label = tamil ? tab.ta : tab.en;
      return (
        <TouchableOpacity
          key={tab.name}
          onPress={() => onChange(tab.name)}
          accessibilityRole="tab"
          accessibilityLabel={`${label}, tab ${index + 1} of ${TABS.length}`}
          accessibilityState={{selected}}
          style={styles.tab}>
          <View style={[styles.marker, selected && styles.markerOn]} />
          <Text
            style={[styles.label, selected && styles.labelOn]}
            numberOfLines={1}
            adjustsFontSizeToFit
            maxFontSizeMultiplier={1.6}>
            {label}
          </Text>
        </TouchableOpacity>
      );
    })}
  </View>
);

const styles = StyleSheet.create({
  bar: {
    flexDirection: 'row',
    backgroundColor: colors.card,
    borderTopWidth: 1,
    borderTopColor: colors.line,
    paddingBottom: 4,
  },
  tab: {
    flex: 1,
    alignItems: 'center',
    minHeight: TOUCH + 8,
    justifyContent: 'center',
    paddingHorizontal: 2,
  },
  marker: {
    position: 'absolute',
    top: 0,
    height: 3,
    width: '60%',
    borderBottomLeftRadius: 3,
    borderBottomRightRadius: 3,
  },
  markerOn: {
    backgroundColor: colors.brand,
  },
  label: {
    color: colors.muted,
    fontSize: 14,
    fontWeight: '600',
    marginTop: 4,
  },
  labelOn: {
    color: colors.brand,
    fontWeight: '800',
  },
});

export default TabBar;
