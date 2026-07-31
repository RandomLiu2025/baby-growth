(function initTime(root, factory) {
  const time = factory();
  if (typeof module === 'object' && module.exports) module.exports = time;
  if (root) root.BabyGrowthTime = time;
}(typeof globalThis !== 'undefined' ? globalThis : this, function createTimeModule() {
  const DATE_KEY_PATTERN = /^(\d{4})-(\d{2})-(\d{2})$/;
  const formatters = new Map();

  function pad(value) {
    return String(value).padStart(2, '0');
  }

  function parseDateKey(value) {
    if (typeof value !== 'string') return null;
    const match = DATE_KEY_PATTERN.exec(value);
    if (!match) return null;
    const year = Number(match[1]);
    const month = Number(match[2]);
    const day = Number(match[3]);
    const candidate = new Date(Date.UTC(year, month - 1, day));
    if (
      candidate.getUTCFullYear() !== year
      || candidate.getUTCMonth() !== month - 1
      || candidate.getUTCDate() !== day
    ) return null;
    return { year, month, day };
  }

  function partsKey(parts) {
    return parts ? `${parts.year}-${pad(parts.month)}-${pad(parts.day)}` : '';
  }

  function browserTimeZone() {
    try {
      return Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';
    } catch (error) {
      return 'UTC';
    }
  }

  function normalizeTimeZone(timeZone) {
    const candidate = timeZone || browserTimeZone();
    try {
      new Intl.DateTimeFormat('en-US', { timeZone: candidate }).format(new Date(0));
      return candidate;
    } catch (error) {
      return 'UTC';
    }
  }

  function formatter(timeZone, withTime) {
    const zone = normalizeTimeZone(timeZone);
    const key = `${zone}:${withTime ? 'datetime' : 'date'}`;
    if (!formatters.has(key)) {
      const options = {
        timeZone: zone,
        calendar: 'gregory',
        numberingSystem: 'latn',
        year: 'numeric',
        month: '2-digit',
        day: '2-digit',
      };
      if (withTime) {
        options.hour = '2-digit';
        options.minute = '2-digit';
        options.hourCycle = 'h23';
      }
      formatters.set(key, new Intl.DateTimeFormat('en-US', options));
    }
    return formatters.get(key);
  }

  function zonedParts(value, timeZone, withTime = false) {
    const instant = value instanceof Date ? new Date(value.getTime()) : new Date(value);
    if (Number.isNaN(instant.getTime())) return null;
    const values = {};
    formatter(timeZone, withTime).formatToParts(instant).forEach(part => {
      if (part.type !== 'literal') values[part.type] = Number(part.value);
    });
    if (![values.year, values.month, values.day].every(Number.isFinite)) return null;
    return {
      year: values.year,
      month: values.month,
      day: values.day,
      hour: Number.isFinite(values.hour) ? values.hour : 0,
      minute: Number.isFinite(values.minute) ? values.minute : 0,
    };
  }

  function dateKey(value, timeZone) {
    const calendar = parseDateKey(value);
    if (calendar) return partsKey(calendar);
    return partsKey(zonedParts(value, timeZone));
  }

  function formatDate(value, timeZone) {
    const parts = parseDateKey(dateKey(value, timeZone));
    return parts ? `${parts.year}年${parts.month}月${parts.day}日` : (value || '');
  }

  function formatMonthDay(value, timeZone) {
    const parts = parseDateKey(dateKey(value, timeZone));
    return parts ? `${parts.month}月${parts.day}日` : (value || '');
  }

  function formatTime(value, timeZone) {
    if (parseDateKey(value)) return '';
    const parts = zonedParts(value, timeZone, true);
    return parts ? `${pad(parts.hour)}:${pad(parts.minute)}` : '';
  }

  function formatDateTime(value, timeZone) {
    const parts = zonedParts(value, timeZone, true);
    return parts ? `${parts.month}/${parts.day} ${pad(parts.hour)}:${pad(parts.minute)}` : (value || '');
  }

  function calendarEpoch(value) {
    const parts = parseDateKey(value);
    return parts ? Date.UTC(parts.year, parts.month - 1, parts.day) : NaN;
  }

  function calendarDaysBetween(start, end) {
    const startEpoch = calendarEpoch(start);
    const endEpoch = calendarEpoch(end);
    if (!Number.isFinite(startEpoch) || !Number.isFinite(endEpoch)) return 0;
    return Math.round((endEpoch - startEpoch) / 86400000);
  }

  function addDays(value, amount) {
    const epoch = calendarEpoch(value);
    if (!Number.isFinite(epoch)) return '';
    const result = new Date(epoch + Math.trunc(Number(amount) || 0) * 86400000);
    return `${result.getUTCFullYear()}-${pad(result.getUTCMonth() + 1)}-${pad(result.getUTCDate())}`;
  }

  function addMonths(value, amount) {
    const parts = parseDateKey(value);
    if (!parts) return '';
    const totalMonths = parts.year * 12 + parts.month - 1 + Math.trunc(Number(amount) || 0);
    const year = Math.floor(totalMonths / 12);
    const monthIndex = ((totalMonths % 12) + 12) % 12;
    const month = monthIndex + 1;
    const lastDay = new Date(Date.UTC(year, month, 0)).getUTCDate();
    return `${year}-${pad(month)}-${pad(Math.min(parts.day, lastDay))}`;
  }

  function addYears(value, amount) {
    return addMonths(value, Math.trunc(Number(amount) || 0) * 12);
  }

  function yearOf(value, timeZone) {
    const parts = parseDateKey(dateKey(value, timeZone));
    return parts ? parts.year : null;
  }

  function monthDay(value, timeZone) {
    const parts = parseDateKey(dateKey(value, timeZone));
    return parts ? `${pad(parts.month)}-${pad(parts.day)}` : '';
  }

  function compareDateValues(left, right, timeZone) {
    return dateKey(left, timeZone).localeCompare(dateKey(right, timeZone));
  }

  function ageText(birthday, referenceDate) {
    const birth = parseDateKey(birthday);
    const reference = parseDateKey(referenceDate);
    if (!birth || !reference) return '';
    let months = (reference.year - birth.year) * 12 + reference.month - birth.month;
    if (reference.day < birth.day) months -= 1;
    months = Math.max(0, months);
    const years = Math.floor(months / 12);
    const remaining = months % 12;
    return `${years ? `${years}岁` : ''}${remaining ? `${remaining}个月` : (years ? '' : '未满月')}`;
  }

  function createBusinessClock(meta = {}, clientNow = () => Date.now()) {
    const timeZone = normalizeTimeZone(meta.timeZone);
    const clientAnchor = Number(clientNow());
    const parsedServer = Date.parse(meta.now || meta.serverNow || '');
    const serverAnchor = Number.isFinite(parsedServer) ? parsedServer : clientAnchor;
    return {
      timeZone,
      now() {
        const elapsed = Number(clientNow()) - clientAnchor;
        return new Date(serverAnchor + (Number.isFinite(elapsed) ? elapsed : 0));
      },
      today() {
        return dateKey(this.now(), timeZone);
      },
    };
  }

  return {
    addDays,
    addMonths,
    addYears,
    ageText,
    calendarDaysBetween,
    compareDateValues,
    createBusinessClock,
    dateKey,
    formatDate,
    formatDateTime,
    formatMonthDay,
    formatTime,
    monthDay,
    normalizeTimeZone,
    parseDateKey,
    yearOf,
  };
}));
