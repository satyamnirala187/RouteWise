// Step 3A: the only places external links are built for riders. Both take validated values and
// return either a link or the reason there is none, so an unusable value never becomes a link.
// Nothing here opens anything: the rider taps the link.

export type LinkResult = { href: string; issue: null } | { href: null; issue: string };

const CONTACT_CHARS = /^[0-9+\-() .]+$/;  // the characters the importer accepts for Contact

/** `tel:` link for a stored contact. The stored string is shown unchanged; only the link is
 * normalised to an optional leading + and 7–15 digits (E.164 allows at most 15). No country
 * code is guessed. */
export function telLink(contact: string | null | undefined): LinkResult {
  const s = (contact ?? "").trim();
  if (!s) return { href: null, issue: "No contact number was imported for this order." };
  if (!CONTACT_CHARS.test(s) || s.lastIndexOf("+") > 0) {
    return { href: null, issue: "This contact is not a single phone number." };
  }
  const digits = s.replace(/\D/g, "");
  if (digits.length < 7 || digits.length > 15 || /^0+$/.test(digits)) {
    return { href: null, issue: "This contact does not have a dialable number of digits." };
  }
  return { href: `tel:${s.startsWith("+") ? "+" : ""}${digits}`, issue: null };
}

/** Google Maps directions to a validated point, in the documented Maps URLs format
 * (https://developers.google.com/maps/documentation/urls/get-started#directions-action):
 * `https://www.google.com/maps/dir/?api=1&destination=<lat>%2C<lng>&travelmode=two-wheeler`.
 * No origin (Google Maps uses its own idea of where the rider is; RouteWise never asks for the
 * device location) and no dir_action=navigate, so Maps opens a route preview and the rider
 * starts navigation there. Google Maps chooses its own road: it is not the planned route. */
export function directionsLink(location: { lat: number; lng: number } | null | undefined, issue?: string | null): LinkResult {
  const fallback = issue || "This order has no usable location.";
  if (!location) return { href: null, issue: fallback };
  const { lat, lng } = location;
  if (typeof lat !== "number" || typeof lng !== "number" || !Number.isFinite(lat) || !Number.isFinite(lng)
      || Math.abs(lat) > 90 || Math.abs(lng) > 180 || (lat === 0 && lng === 0)) {
    return { href: null, issue: fallback };
  }
  const url = new URL("https://www.google.com/maps/dir/");
  url.searchParams.set("api", "1");
  url.searchParams.set("destination", `${lat.toFixed(6)},${lng.toFixed(6)}`);
  url.searchParams.set("travelmode", "two-wheeler");
  return { href: url.toString(), issue: null };
}
