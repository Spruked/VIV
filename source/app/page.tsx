import Link from 'next/link';
import { PrimaryLogo } from '@/components/brand/PrimaryLogo';
import {Button}  from '@/components/ui/Button';
import { Input } from '@/components/ui/Input';
import { Section } from '@/components/ui/Section';

export default function Home() {
  return (
    <>
      <Section bleed className="relative flex min-h-[90vh] flex-col items-center justify-center text-center">
        <div className="absolute inset-0 opacity-5">
          <PrimaryLogo size={800} className="absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2" />
        </div>
        <PrimaryLogo size={180} className="mb-8" />
        <h1 className="mb-6 text-6xl font-black uppercase leading-none tracking-tight sm:text-8xl">
          You&rsquo;ve been
          <br />
          <span className="text-truth">Spruked</span>
        </h1>
        <p className="mb-6 max-w-2xl text-2xl font-bold text-white uppercase tracking-widest sm:text-3xl">
          "If better is possible, good is simply not enough."
        </p>
        <p className="mb-6 max-w-2xl text-xl text-gray-400 sm:text-2xl">
          Truth with teeth. Precision correction. No fluff. No mercy.
        </p>
        <p className="mb-3 max-w-3xl text-2xl font-semibold text-white sm:text-3xl">
          Spruked <span className="text-truth">-</span> Where Objects Tell the Truth.
        </p>
        <p className="mb-12 max-w-3xl text-xl text-gray-300 sm:text-2xl">
          A registry for verified records, provenance, and intelligent object profiles.
        </p>
        <div className="mb-16 flex flex-col gap-6 sm:flex-row">
          <Button size="lg" asChild>
            <Link href="#waitlist">Get Spruked</Link>
          </Button>
          <Button size="lg" variant="outline" asChild>
            <a href="mailto:bryan@spruked.com">Contact</a>
          </Button>
          <Button size="lg" variant="outline" asChild>
            <Link href="/orb-skin-studio">Orb Skin Studio Demo</Link>
          </Button>
        </div>
      </Section>

      <Section className="mx-auto max-w-5xl">
        <h2 className="mb-12 text-5xl font-black leading-tight sm:text-7xl">
          What does it mean to be <span className="text-truth">Spruked</span>?
        </h2>
        <div className="space-y-8 text-2xl text-gray-300">
          <p>Spruking is the act of delivering correction with precision and authority.</p>
          <p>It&rsquo;s not vague feedback. It&rsquo;s not polite criticism.</p>
          <p className="text-3xl font-semibold text-light">
            It&rsquo;s the moment someone who knows better steps in and says:
            <br />
            <span className="text-truth">“Here&rsquo;s what you missed. Here&rsquo;s what&rsquo;s actually true. Here&rsquo;s how to fix it.”</span>
          </p>
        </div>
      </Section>

      <Section className="mx-auto max-w-5xl py-12">
        <div className="rounded-xl border border-truth/30 bg-truth/5 p-10 text-center shadow-[0_0_30px_rgba(255,255,255,0.05)]">
          <h2 className="mb-6 text-3xl font-black uppercase tracking-widest text-truth">
            TrueMark Objects
          </h2>
          <p className="mb-8 text-2xl sm:text-3xl font-bold text-white leading-tight">
            TrueMark Objects transform knowledge, expertise, and meaningful digital artifacts into verified digital records that can be preserved, licensed, traded, or inherited across generations.
          </p>
          <Button size="lg" variant="outline" className="border-truth/50 hover:bg-truth/10" asChild>
            <Link href="/products/truemark-mint/objects">Understand the Object Model</Link>
          </Button>
        </div>
      </Section>

      {/* The Spruked Knowledge Infrastructure */}
      <Section className="mx-auto max-w-6xl py-24">
        <h2 className="text-4xl sm:text-5xl font-bold text-center mb-6 text-white">
          The Spruked Knowledge Infrastructure
        </h2>
        <p className="text-center text-xl text-gray-400 mb-16">
          Two systems working together to preserve knowledge and digital artifacts.
        </p>

        <div className="grid md:grid-cols-2 gap-10 items-center">
          {/* Alpha CertSig */}
          <div className="border border-gray-700 rounded-xl p-8 bg-[#050505] flex flex-col h-full relative">
            <h3 className="text-3xl font-bold mb-4 text-white">
              Alpha CertSig <span className="text-sm font-normal uppercase tracking-widest text-gray-500 block mt-1">Engine</span>
            </h3>
            <p className="text-xl text-gray-400 mb-6 flex-grow">
              Licensed mint engine infrastructure used by institutions, creators, and enterprises to generate forensic digital objects.
            </p>
            <div className="text-sm font-bold text-gray-500 uppercase tracking-widest">
              Self-hosted • Sovereign • No per-mint fees
            </div>
            
            {/* Arrow indicating flow to registry on desktop */}
            <div className="hidden md:block absolute -right-8 top-1/2 -translate-y-1/2 text-gray-600">
              <svg width="24" height="24" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                <path d="M5 12H19M19 12L12 5M19 12L12 19" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
              </svg>
            </div>
            {/* Arrow indicating flow to registry on mobile */}
            <div className="block md:hidden absolute -bottom-8 left-1/2 -translate-x-1/2 text-gray-600">
              <svg width="24" height="24" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                <path d="M12 5V19M12 19L5 12M12 19L19 12" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
              </svg>
            </div>
          </div>

          {/* TrueMark */}
          <div className="border border-truth/40 rounded-xl p-8 bg-truth/5 shadow-[0_0_30px_rgba(255,255,255,0.05)] flex flex-col h-full">
            <h3 className="text-3xl font-bold mb-4 text-truth">
              TrueMark <span className="text-sm font-normal uppercase tracking-widest text-gray-400 block mt-1">Registry</span>
            </h3>
            <p className="text-xl text-gray-300 mb-6 flex-grow">
              The curated archive of verified digital knowledge objects created within the Spruked ecosystem.
            </p>
            <div className="text-sm font-bold text-truth/80 uppercase tracking-widest">
              Authorship • Preservation • Attribution
            </div>
          </div>
        </div>

        {/* NFT Types */}
        <div className="mt-16 grid grid-cols-2 md:grid-cols-5 gap-4 text-center">
          <Link href="/products/truemark-mint/object-types" className="bg-[#050505] rounded-xl p-6 border border-gray-800 hover:border-gray-600 transition-colors group">
            <p className="font-mono text-xl font-bold text-white group-hover:text-truth transition-colors">K-NFT</p>
            <p className="text-sm text-gray-400 mt-2 font-medium">Knowledge</p>
          </Link>
          <Link href="/products/truemark-mint/object-types" className="bg-[#050505] rounded-xl p-6 border border-gray-800 hover:border-gray-600 transition-colors group">
            <p className="font-mono text-xl font-bold text-white group-hover:text-truth transition-colors">KL-NFT</p>
            <p className="text-sm text-gray-400 mt-2 font-medium">Licensed Knowledge</p>
          </Link>
          <Link href="/products/truemark-mint/object-types" className="bg-[#050505] rounded-xl p-6 border border-gray-800 hover:border-gray-600 transition-colors group">
            <p className="font-mono text-xl font-bold text-white group-hover:text-truth transition-colors">H-NFT</p>
            <p className="text-sm text-gray-400 mt-2 font-medium">Heirloom</p>
          </Link>
          <Link href="/products/truemark-mint/object-types" className="bg-[#050505] rounded-xl p-6 border border-gray-800 hover:border-gray-600 transition-colors group">
            <p className="font-mono text-xl font-bold text-white group-hover:text-truth transition-colors">L-NFT</p>
            <p className="text-sm text-gray-400 mt-2 font-medium">Legacy</p>
          </Link>
          <Link href="/products/truemark-mint/object-types" className="bg-truth/10 rounded-xl p-6 border border-truth/30 hover:border-truth/60 transition-colors group col-span-2 md:col-span-1">
            <p className="font-mono text-xl font-bold text-truth">E-NFT</p>
            <p className="text-sm text-gray-300 mt-2 font-medium">Enterprise</p>
          </Link>
        </div>

        {/* Example TrueMark Object */}
        <div className="mt-20 border border-gray-800 bg-[#050505] p-8 rounded-xl max-w-5xl mx-auto flex flex-col md:flex-row gap-10 items-start">
          <div className="flex-1 w-full">
            <img 
              src="/assets/CertificateKNFTsample.png" 
              alt="K-NFT Spruked Certificate Sample" 
              className="w-full h-auto rounded-lg border border-gray-800 shadow-[0_0_30px_rgba(255,255,255,0.05)]" 
            />
            <div className="mt-4 text-sm text-gray-400 bg-black/40 border border-gray-900 p-4 rounded-lg">
              <strong className="text-white block mb-1">Example K-NFT Certificate</strong>
              This certificate was generated by the Alpha CertSig engine and represents a verified Knowledge Object issued within the TrueMark registry.
            </div>
          </div>
          <div className="flex-1 font-mono text-sm sm:text-base w-full">
            <p className="text-white mb-6 border-b border-gray-800 pb-2 text-xl font-bold font-sans">Object Metadata</p>
            <div className="space-y-4 text-gray-300">
               <div className="flex flex-col sm:flex-row gap-2 sm:gap-8 border-b border-gray-900 pb-2">
                 <span className="text-gray-500 w-24 uppercase tracking-widest font-sans text-xs">Identifier:</span>
                 <span className="text-truth font-bold bg-truth/10 px-1 rounded">K-NFT-SPRUK-ENG-2026-000014</span>
               </div>
               <div className="flex flex-col sm:flex-row gap-2 sm:gap-8 border-b border-gray-900 pb-2">
                 <span className="text-gray-500 w-24 uppercase tracking-widest font-sans text-xs">Artifact:</span>
                 <span className="text-white">Precision Lathe Retrofit Method</span>
               </div>
               <div className="flex flex-col sm:flex-row gap-2 sm:gap-8 border-b border-gray-900 pb-2">
                 <span className="text-gray-500 w-24 uppercase tracking-widest font-sans text-xs">Creator:</span>
                 <span className="text-white">Bryan Spruk</span>
               </div>
               <div className="flex flex-col sm:flex-row gap-2 sm:gap-8 border-b border-gray-900 pb-2">
                 <span className="text-gray-500 w-24 uppercase tracking-widest font-sans text-xs">License:</span>
                 <span className="text-white">Educational + Commercial</span>
               </div>
               <div className="flex flex-col sm:flex-row gap-2 sm:gap-8 pt-2">
                 <span className="text-gray-500 w-24 uppercase tracking-widest font-sans text-xs">Status:</span>
                 <div>
                   <span className="text-[#00ff00]">Active / Verified</span>

              <Section className="mx-auto max-w-5xl py-16 border-t border-gray-900">
                <div className="rounded-xl border border-gray-800 bg-[#050505] p-8 sm:p-10">
                  <p className="mb-3 text-xs font-bold uppercase tracking-[0.2em] text-truth">Founder Statement</p>
                  <h2 className="mb-6 text-3xl font-black leading-tight text-light sm:text-4xl">
                    A real builder. A direct path. A long-term commitment.
                  </h2>
                  <div className="space-y-5 text-lg text-gray-300">
                    <p>
                      My name is Bryan Spruk. I built this ecosystem through practical work, not a traditional track: sales, business development, welding, machining, entrepreneurship, and years of solving real problems with limited resources.
                    </p>
                    <p>
                      My focus is simple: build local-first, privacy-conscious systems that help people preserve knowledge, protect ownership, and operate with more control over their data and digital presence.
                    </p>
                    <p>
                      I do not claim a perfect resume. I do claim honesty, discipline, and continued execution. My goal is not to appear perfect. My goal is to build something worth trusting.
                    </p>
                  </div>
                  <div className="mt-8">
                    <Button variant="outline" asChild>
                      <Link href="/about">Read Full Founder Background</Link>
                    </Button>
                  </div>
                </div>
              </Section>
                   <div className="flex flex-wrap gap-2 mt-4 font-sans">
                     <span className="text-xs bg-gray-900 border border-gray-700 text-gray-300 px-2 py-1 rounded">10-Layer Forensic</span>
                     <span className="text-xs bg-gray-900 border border-gray-700 text-gray-300 px-2 py-1 rounded">ChaCha20 Encryption</span>
                     <span className="text-xs bg-gray-900 border border-gray-700 text-gray-300 px-2 py-1 rounded">Registry Verified</span>
                   </div>
                 </div>
               </div>
               
               {/* Engine Verification details */}
               <div className="mt-8 pt-6 border-t border-gray-800 font-sans">
                 <h4 className="text-white text-sm font-bold uppercase tracking-widest mb-3">Object Verification</h4>
                 <p className="text-sm text-gray-400 mb-4">This artifact was issued using the Alpha CertSig engine.</p>
                 <ul className="text-sm text-gray-300 space-y-2 mb-6">
                   <li className="flex items-center gap-2"><div className="w-1.5 h-1.5 bg-truth rounded-full"></div> File Integrity Verification</li>
                   <li className="flex items-center gap-2"><div className="w-1.5 h-1.5 bg-truth rounded-full"></div> Cryptographic Signature</li>
                   <li className="flex items-center gap-2"><div className="w-1.5 h-1.5 bg-truth rounded-full"></div> Metadata Preservation</li>
                   <li className="flex items-center gap-2"><div className="w-1.5 h-1.5 bg-truth rounded-full"></div> Timestamp Record</li>
                   <li className="flex items-center gap-2"><div className="w-1.5 h-1.5 bg-truth rounded-full"></div> Certificate Rendering</li>
                 </ul>
               </div>

               <div className="pt-2">
                 <Button variant="outline" className="w-full text-truth border-truth/30 hover:border-truth/80" asChild>
                   <Link href="/truemark/example-object">View Full Object Page &rarr;</Link>
                 </Button>
               </div>
            </div>
          </div>
        </div>
      </Section>

      {/* Platform Status Section */}
      <Section className="mx-auto max-w-5xl py-12 border-t border-gray-900">
        <div className="flex flex-col sm:flex-row items-center justify-between mb-8 pb-4 border-b border-gray-800">
          <div className="flex items-center gap-4">
            <div className="relative flex h-4 w-4">
              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-truth opacity-75"></span>
              <span className="relative inline-flex rounded-full h-4 w-4 bg-truth"></span>
            </div>
            <h2 className="text-xl font-bold uppercase tracking-widest text-white">System Status</h2>
          </div>
          <p className="mt-4 sm:mt-0 text-sm font-bold text-truth tracking-widest uppercase">All Systems Operational</p>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-6">
          <div className="bg-[#0a0a0a] border border-gray-800 rounded-lg p-5">
            <h3 className="text-sm font-semibold text-gray-400 uppercase tracking-wider mb-2">Alpha CertSig Engine</h3>
            <div className="flex items-center gap-2 mb-1">
              <div className="h-2 w-2 bg-[#00ff00] rounded-full"></div>
              <span className="text-white font-mono">Operational</span>
            </div>
            <p className="text-xs text-gray-600">Global Mint Network</p>
          </div>

          <div className="bg-[#0a0a0a] border border-gray-800 rounded-lg p-5">
            <h3 className="text-sm font-semibold text-gray-400 uppercase tracking-wider mb-2">TrueMark Registry</h3>
            <div className="flex items-center gap-2 mb-1">
              <div className="h-2 w-2 bg-[#00ff00] rounded-full"></div>
              <span className="text-white font-mono">Active</span>
            </div>
            <p className="text-xs text-gray-600">Immutable Record</p>
          </div>

          <div className="bg-[#0a0a0a] border border-gray-800 rounded-lg p-5">
            <h3 className="text-sm font-semibold text-gray-400 uppercase tracking-wider mb-2">ORB Interface</h3>
            <div className="flex items-center gap-2 mb-1">
              <div className="h-2 w-2 bg-yellow-500 rounded-full"></div>
              <span className="text-yellow-500 font-mono">Development</span>
            </div>
            <p className="text-xs text-yellow-500/60">Low Latency Core</p>
          </div>

          <div className="bg-[#0a0a0a] border border-gray-800 rounded-lg p-5">
            <h3 className="text-sm font-semibold text-gray-400 uppercase tracking-wider mb-2">Pro Prime Engine</h3>
            <div className="flex items-center gap-2 mb-1">
              <div className="h-2 w-2 bg-purple-500 rounded-full"></div>
              <span className="text-purple-400 font-mono">Research</span>
            </div>
            <p className="text-xs text-gray-600">Model Routing</p>
          </div>
        </div>
      </Section>

      <Section id="waitlist" className="bg-gradient-to-b from-dark to-black">
        <div className="mx-auto max-w-3xl text-center">
          <p className="mb-5 text-lg text-gray-300 sm:text-xl">
            Become a Spruikster - someone who doesn&rsquo;t just talk things up, but sets things straight.
          </p>
          <h2 className="mb-8 text-5xl font-black uppercase leading-tight sm:text-7xl">
            Ready to be <span className="text-truth">Spruked</span>?
          </h2>
          <p className="mb-10 text-lg text-gray-400">Join the private waitlist. First 100 receive lifetime status.</p>
          <form action="/api/waitlist" method="post" className="mx-auto flex max-w-xl flex-col gap-4">
            <select
              id="waitlist-lead-type"
              name="leadType"
              defaultValue="promoter"
              className="rounded-full border border-gray-700 bg-black px-5 py-5 text-center text-sm font-semibold uppercase tracking-[0.2em] text-light"
            >
              <option value="promoter">Promoter</option>
              <option value="investor">Investor</option>
              <option value="marketing">Marketing Contact</option>
              <option value="business">Business Contact</option>
            </select>
            <Input
              id="waitlist-email"
              name="email"
              type="email"
              autoComplete="email"
              placeholder="you@truth.com"
              required
              className="py-5 text-lg"
            />
            <input id="waitlist-source" name="source" type="hidden" value="homepage_waitlist" />
            <Button size="lg" className="w-full justify-center py-5 text-lg text-center">
              Secure My Spot
            </Button>
          </form>
        </div>
      </Section>
    </>
  );
}
