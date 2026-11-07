import React from 'react';
import {StyleSheet, Text, TouchableOpacity, View} from 'react-native';

import {colors} from '../theme';

export type TabName = 'home' | 'assistant' | 'shop' | 'send' | 'history' | 'profile';

type Props = {
  current: TabName;
  onChange: (tab: TabName) => void;
  tamil: boolean;
};

const TABS: {name: TabName; icon: string; en: string; ta: string}[] = [
  {name: 'home', icon: '🏠', en: 'Home', ta: 'முகப்பு'},
  {name: 'assistant', icon: '💬', en: 'Chat', ta: 'அரட்டை'},
  {name: 'shop', icon: '🛒', en: 'Shop', ta: 'கடை'},
  {name: 'send', icon: '💸', en: 'Send', ta: 'அனுப்பு'},
  {name: 'history', icon: '📍', en: 'Track', ta: 'கண்காணி'},
  {name: 'profile', icon: '👤', en: 'Profile', ta: 'சுயவிவரம்'},
];

const TabBar = ({current, onChange, tamil}: Props) => (
  <View style={styles.bar} accessibilityRole="tablist">
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
          style={[styles.tab, selected && styles.tabSelected]}>
          <Text style={styles.icon} importantForAccessibility="no">
            {tab.icon}
          </Text>
          <Text
            style={[styles.label, selected && styles.labelSelected]}
            numberOfLines={1}>
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
    backgroundColor: colors.navy,
    paddingVertical: 6,
    paddingHorizontal: 4,
  },
  tab: {
    flex: 1,
    alignItems: 'center',
    paddingVertical: 6,
    borderRadius: 10,
    minHeight: 52,
    justifyContent: 'center',
  },
  tabSelected: {
    backgroundColor: '#263449',
  },
  icon: {
    fontSize: 20,
  },
  label: {
    color: '#C7D2E3',
    fontSize: 11,
    marginTop: 2,
  },
  labelSelected: {
    color: '#FFFFFF',
    fontWeight: '800',
  },
});

export default TabBar;
