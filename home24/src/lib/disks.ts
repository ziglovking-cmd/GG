export const PUBLIC_DISKS = {
  main: "https://disk.yandex.ru/d/ZLKt8eDXJYKdnQ",
  lunar: "https://disk.yandex.ru/d/qEcIlAwweu9PVQ",
  salaryevo: "https://disk.yandex.ru/d/F0fTNy2NXCWrSg",
  matiss: "https://disk.yandex.ru/d/FU-ezcYY42tGjw",
  homlin: "https://disk.yandex.ru/d/hMG8nsN7pgBzew",
  artmen: "https://disk.yandex.ru/d/u7W9-FhP5WI6ug",
  voyazh: "https://disk.yandex.ru/d/sgoDpoIgFACMOQ",
  briz: "https://disk.yandex.ru/d/qHH59Igb1tedqA",
  ferrari: "https://disk.yandex.ru/d/JgDRbxlWFoZagw",
} as const;

export type DiskId = keyof typeof PUBLIC_DISKS;

export const DISK_UA =
  "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36";
