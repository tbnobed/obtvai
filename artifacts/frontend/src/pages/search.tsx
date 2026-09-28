import { useEffect } from "react";
import { useLocation, useSearch } from "wouter";
import { legacySearchRedirect } from "@/lib/library-search";

/** Search now lives in the Media Library; keep old /search?q=&scope= links working. */
export default function SearchRedirect() {
  const searchString = useSearch();
  const [, navigate] = useLocation();
  useEffect(() => { navigate(legacySearchRedirect(searchString), { replace: true }); }, [searchString, navigate]);
  return null;
}
