import { describe, expect, it } from "vitest";
import { directionsLink, telLink } from "./links";

describe("telLink", () => {
  it("keeps the digits and a leading + only", () => {
    expect(telLink("+91 00000-00001")).toEqual({ href: "tel:+910000000001", issue: null });
    expect(telLink("(011) 0000.0001")).toEqual({ href: "tel:01100000001", issue: null });
    expect(telLink(" 0000000123 ")).toEqual({ href: "tel:0000000123", issue: null });
  });
  it("refuses missing, mixed or implausible contacts with a reason", () => {
    for (const bad of ["", "   ", null, undefined]) expect(telLink(bad)).toMatchObject({ href: null, issue: expect.stringContaining("No contact") });
    for (const bad of ["call 0000000123", "0000000123 / 0000000124", "0000000123,0000000124", "00000+00123", "++910000000001",
      "tel:0000000123", "javascript:alert(1)", "0000000123;ext=2"]) {
      expect(telLink(bad).href, bad).toBeNull();
    }
    for (const bad of ["123456", "1234567890123456", "000-0000", "+"]) expect(telLink(bad).href, bad).toBeNull();
  });
});

describe("directionsLink", () => {
  it("builds the documented Maps URLs directions link with an encoded destination", () => {
    const { href } = directionsLink({ lat: 28.6889001, lng: 77.2100009 });
    expect(href).toBe("https://www.google.com/maps/dir/?api=1&destination=28.688900%2C77.210001&travelmode=two-wheeler");
    const u = new URL(href!);
    expect(u.origin + u.pathname).toBe("https://www.google.com/maps/dir/");
    expect(u.searchParams.get("origin")).toBeNull();      // never the rider's position
    expect(u.searchParams.get("dir_action")).toBeNull();  // never starts navigation by itself
  });
  it("gives no link for missing or invalid coordinates and passes the server's reason on", () => {
    expect(directionsLink(null, "This order's location needs correction by your admin.")).toEqual(
      { href: null, issue: "This order's location needs correction by your admin." });
    for (const bad of [{ lat: NaN, lng: 77.2 }, { lat: 28.7, lng: Infinity }, { lat: 91, lng: 77.2 }, { lat: 28.7, lng: -181 },
      { lat: 0, lng: 0 }, { lat: "28.7", lng: "77.2" } as unknown as { lat: number; lng: number }]) {
      expect(directionsLink(bad).href).toBeNull();
    }
  });
});
