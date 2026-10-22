export function getSafeNextPath(next: string | null, origin: string) {
  if (!next || !next.startsWith("/") || next.startsWith("//")) {
    return "/admin";
  }

  let decodedNext: string;
  try {
    decodedNext = decodeURIComponent(next);
  } catch {
    return "/admin";
  }

  if (decodedNext.includes("\\")) {
    return "/admin";
  }

  const redirectUrl = new URL(decodedNext, origin);
  if (redirectUrl.origin !== origin) {
    return "/admin";
  }

  return `${redirectUrl.pathname}${redirectUrl.search}${redirectUrl.hash}`;
}
