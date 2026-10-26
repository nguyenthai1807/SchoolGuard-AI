// More effort samples more frames, not a promise of higher per-frame accuracy.
export const EFFORTS=Object.freeze({
  low:{intervalMs:1000,label:'Low · tiết kiệm pin'},
  medium:{intervalMs:600,label:'Medium · cân bằng'},
  high:{intervalMs:300,label:'High · quan sát thường hơn'},
  extra:{intervalMs:150,label:'Extra · xử lý nhiều hơn'},
  extra_max:{intervalMs:80,label:'Extra Max · tải máy cao'},
});
export function effortInterval(value){return (EFFORTS[value]||EFFORTS.medium).intervalMs;}
