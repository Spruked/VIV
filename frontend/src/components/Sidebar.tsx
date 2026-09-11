import { Activity, Bot, Calendar, Home, KanbanSquare, Mail, ShieldAlert, Users } from 'lucide-react'
import { NavLink } from 'react-router-dom'
import { cn } from '@/lib/utils'

const coreNavItems = [
  { icon: Home, label: 'Command Center', path: '/' },
  { icon: Users, label: 'Dossier Vault', path: '/contacts' },
  { icon: Mail, label: 'Communications', path: '/email' },
  { icon: Activity, label: 'Timeline', path: '/activities' },
  { icon: Calendar, label: 'Event Grid', path: '/calendar' },
  { icon: ShieldAlert, label: 'Escalations', path: '/escalations' },
  { icon: Bot, label: 'Command Node', path: '/orb' },
]

const featureNavItems = [
  { icon: KanbanSquare, label: 'Operation Board', path: '/pipeline' },
]

function NavigationLink({ icon: Icon, label, path }: { icon: typeof Home; label: string; path: string }) {
  return (
    <NavLink
      to={path}
      className={({ isActive }) =>
        cn(
          'group flex h-11 items-center gap-3 rounded-2xl px-4 text-sm font-medium transition-all',
          isActive
            ? 'bg-[#1d4ed8]/35 text-white shadow-inner shadow-[#1d4ed8]/40'
            : 'text-cyan-100/70 hover:bg-[#0f1b3d] hover:text-cyan-100',
        )
      }
    >
      <Icon className="size-5 transition-transform group-hover:scale-110" />
      <span>{label}</span>
    </NavLink>
  )
}

export function Sidebar() {
  return (
    <aside className="flex h-screen w-72 shrink-0 flex-col border-r border-blue-900/70 bg-[#0b0f2a]">
      <div className="border-b border-blue-900/70 p-6">
        <div className="mb-3 flex items-center gap-3">
          <img src="/VIVLOGO.png" alt="VIV" className="size-16 rounded-xl object-cover brightness-125 saturate-150 drop-shadow-[0_0_34px_rgb(0,194,255)]" />
          <div>
            <h1 className="text-3xl font-bold tracking-[-2px] text-white">VIV</h1>
            <p className="-mt-1 text-[10px] tracking-[2px] text-cyan-300">VECTOR INTELLIGENCE VAULT</p>
          </div>
        </div>
        <p className="mt-4 text-xs leading-tight text-cyan-100/70">LIFE MANAGEMENT & NAVIGATION SYSTEM</p>
        <p className="mt-1 text-[10px] text-[#7c3aed]/90">Know before you need to know.</p>
      </div>

      <nav className="flex flex-1 flex-col gap-1 overflow-y-auto px-3 py-6">
        {coreNavItems.map((item) => <NavigationLink key={item.path} {...item} />)}
        <div className="mb-1 mt-5 px-4 text-[10px] font-semibold uppercase tracking-[0.16em] text-cyan-100/35">Operations</div>
        {featureNavItems.map((item) => <NavigationLink key={item.path} {...item} />)}
      </nav>

      <div className="mt-auto border-t border-blue-900/70 p-4">
        <p className="text-center text-[10px] text-cyan-100/45">Be Smart. Be Informed. Be Ready.</p>
        <p className="mt-1 text-center text-[10px] text-cyan-100/35">2026 Spruked - VIV</p>
      </div>
    </aside>
  )
}
