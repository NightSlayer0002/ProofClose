export function formatINR(paise: number): string {
  const negative = paise < 0
  const absolute = Math.abs(paise)
  const rupees = Math.floor(absolute / 100)
  const subunits = absolute % 100
  const grouped = rupees.toLocaleString('en-IN')
  return `${negative ? '-' : ''}₹${grouped}.${subunits.toString().padStart(2, '0')}`
}

export function formatAge(iso: string): string {
  const milliseconds = Date.now() - new Date(iso).getTime()
  const hours = Math.max(0, Math.floor(milliseconds / 3_600_000))
  return hours < 24 ? `${hours}h` : `${Math.floor(hours / 24)}d`
}

export function sentenceCase(value: string): string {
  return value
    .toLowerCase()
    .split('_')
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(' ')
}

