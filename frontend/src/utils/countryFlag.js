/** Превращает ISO alpha-2 код страны в эмодзи-флаг (региональные индикаторы). */
export function countryFlag(code) {
  if (!code || !/^[A-Z]{2}$/.test(code)) return ''
  return String.fromCodePoint(...[...code].map(c => 0x1F1E6 + c.charCodeAt(0) - 65))
}
