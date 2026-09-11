import React, { useEffect, useState } from "react";
import { ExternalLink, Globe, Link2, MapPin, RefreshCw, Search, Trash2 } from "lucide-react";

type ExternalLinkNode = {
  id: number;
  contact_id: string;
  platform: string;
  label: string;
  url: string;
  link_type: string;
  verified_status: string;
  source: string;
};

const PLATFORM_ICONS: Record<string, { icon: React.ReactNode; color: string }> = {
  google_search: { icon: <Search size={14} />, color: "text-blue-400 hover:bg-blue-950/40" },
  google_maps: { icon: <MapPin size={14} />, color: "text-emerald-400 hover:bg-emerald-950/40" },
  facebook: { icon: <Link2 size={14} />, color: "text-indigo-400 hover:bg-indigo-950/40" },
  linkedin: { icon: <Link2 size={14} />, color: "text-cyan-400 hover:bg-cyan-950/40" },
  github: { icon: <Link2 size={14} />, color: "text-purple-400 hover:bg-purple-950/40" },
  domain_lookup: { icon: <Globe size={14} />, color: "text-amber-400 hover:bg-amber-950/40" },
  company_website: { icon: <Globe size={14} />, color: "text-zinc-400 hover:bg-zinc-800/40" },
  custom: { icon: <Link2 size={14} />, color: "text-teal-400 hover:bg-teal-950/40" },
};

const STATUS_BADGES: Record<string, string> = {
  generated_search: "border-amber-500/30 text-amber-500 bg-amber-950/20",
  detected: "border-blue-500/30 text-blue-400 bg-blue-950/20",
  verified: "border-emerald-500/30 text-emerald-400 bg-emerald-950/20",
  manual: "border-zinc-500/30 text-zinc-300 bg-zinc-800/20",
  broken: "border-rose-500/30 text-rose-400 bg-rose-950/20",
};

type Props = {
  contactId: string;
  adminToken?: string;
  apiBase?: string;
};

export default function DossierLinksRibbon({
  contactId,
  adminToken,
  apiBase = "http://127.0.0.1:21000/cali/contacts",
}: Props) {
  const [links, setLinks] = useState<ExternalLinkNode[]>([]);
  const [loading, setLoading] = useState(false);

  const authHeaders = adminToken
    ? { Authorization: `Bearer ${adminToken}` }
    : {};

  const fetchLinks = async () => {
    try {
      const res = await fetch(`${apiBase}/${contactId}/external-links`, { headers: authHeaders });
      if (res.ok) {
        const data = (await res.json()) as ExternalLinkNode[];
        setLinks(data);
      }
    } catch (err) {
      console.error("Failed to sync dossier links from authoritative backend", err);
    }
  };

  const handleGenerate = async () => {
    setLoading(true);
    try {
      await fetch(`${apiBase}/${contactId}/external-links/generate`, {
        method: "POST",
        headers: authHeaders,
      });
      await fetchLinks();
    } catch (err) {
      console.error("Generation error", err);
    } finally {
      setLoading(false);
    }
  };

  const handleDelete = async (e: React.MouseEvent<HTMLButtonElement>, id: number) => {
    e.stopPropagation();
    e.preventDefault();
    if (!window.confirm("Sever link node from dossier?")) return;
    try {
      const res = await fetch(`${apiBase}/${contactId}/external-links/${id}`, {
        method: "DELETE",
        headers: authHeaders,
      });
      if (res.ok) await fetchLinks();
    } catch (err) {
      console.error("Deletion error", err);
    }
  };

  const executeLink = (url: string) => {
    const electronApi = (window as unknown as { electron?: { shell?: { openExternal: (u: string) => void } } }).electron;
    if (electronApi?.shell?.openExternal) {
      electronApi.shell.openExternal(url);
      return;
    }
    window.open(url, "_blank", "noopener,noreferrer");
  };

  useEffect(() => {
    if (contactId) {
      void fetchLinks();
    }
  }, [contactId]);

  return (
    <div className="w-full bg-zinc-950 border border-zinc-800 p-3 font-mono rounded">
      <div className="flex items-center justify-between border-b border-zinc-800 pb-2 mb-2">
        <div className="flex items-center gap-2">
          <span className="text-xs font-bold text-zinc-400 tracking-wider uppercase">Dossier Execution Layer</span>
          <span className="text-[10px] bg-zinc-900 px-1.5 py-0.5 text-zinc-500 rounded border border-zinc-800">
            {links.length} nodes indexed
          </span>
        </div>
        <button
          onClick={handleGenerate}
          disabled={loading}
          className="flex items-center gap-1 text-[11px] bg-blue-950/40 border border-blue-900 hover:bg-blue-900/60 text-blue-400 px-2 py-0.5 rounded transition-all disabled:opacity-50"
        >
          <RefreshCw size={10} className={loading ? "animate-spin" : ""} />
          Generate Fallbacks
        </button>
      </div>

      {links.length === 0 ? (
        <div className="text-[11px] text-zinc-600 italic py-1">
          No identity verification pathways instantiated for this profile. Click generate to build fallbacks.
        </div>
      ) : (
        <div className="flex flex-wrap gap-2">
          {links.map((link) => {
            const displayConfig = PLATFORM_ICONS[link.platform] || PLATFORM_ICONS.custom;
            return (
              <div
                key={link.id}
                onClick={() => executeLink(link.url)}
                className={`group flex items-center gap-2 text-xs border border-zinc-800 bg-zinc-900/60 px-2 py-1 rounded cursor-pointer transition-all ${displayConfig.color}`}
                title={`Target: ${link.url}\nType: ${link.link_type}\nSource: ${link.source}`}
              >
                <div className="flex items-center gap-1.5">
                  {displayConfig.icon}
                  <span className="text-zinc-300 font-medium">{link.label}</span>
                </div>
                <span className={`text-[9px] px-1 rounded border uppercase tracking-tighter ${STATUS_BADGES[link.verified_status] || STATUS_BADGES.manual}`}>
                  {link.verified_status.replace("_", " ")}
                </span>
                <ExternalLink size={10} className="opacity-40 group-hover:opacity-100" />
                <button
                  onClick={(e) => void handleDelete(e, link.id)}
                  className="ml-1 opacity-0 group-hover:opacity-100 text-zinc-600 hover:text-rose-400 transition-opacity"
                  title="Purge Link Node"
                >
                  <Trash2 size={11} />
                </button>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
