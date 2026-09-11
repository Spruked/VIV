import { useEffect, useState } from 'react'
import { AnimatePresence, motion } from 'framer-motion'

export default function SplashScreen({ onComplete }: { onComplete: () => void }) {
  const [progress, setProgress] = useState(0)

  useEffect(() => {
    const timer = window.setInterval(() => {
      setProgress((current) => {
        const next = current + 11
        if (next >= 100) {
          window.clearInterval(timer)
          window.setTimeout(onComplete, 320)
          return 100
        }
        return next
      })
    }, 70)

    return () => window.clearInterval(timer)
  }, [onComplete])

  return (
    <AnimatePresence>
      <motion.div
        className="fixed inset-0 z-50 flex items-center justify-center overflow-hidden bg-[#0b0f2a]"
        initial={{ opacity: 1 }}
        exit={{ opacity: 0 }}
      >
        <div className="absolute inset-0 bg-[radial-gradient(#1d4ed820_1px,transparent_1px)] bg-[length:40px_40px]" />
        <div className="absolute inset-0 bg-[radial-gradient(circle_at_center,rgba(0,194,255,0.18),transparent_34rem)]" />

        <div className="relative z-10 flex flex-col items-center text-center">
          <motion.div
            initial={{ scale: 0.62, opacity: 0 }}
            animate={{ scale: 1, opacity: 1 }}
            transition={{ duration: 0.65, ease: 'easeOut' }}
            className="relative mb-8"
          >
            <img src="/VIVLOGO.png" alt="VIV" className="size-48 rounded-3xl object-cover brightness-125 saturate-150 drop-shadow-[0_0_96px_rgb(0,194,255)]" />
            <motion.div
              className="absolute inset-0 rounded-full border border-[#7c3aed]/40"
              animate={{ rotate: 360 }}
              transition={{ duration: 25, repeat: Infinity, ease: 'linear' }}
            />
            <motion.div
              className="absolute inset-3 rounded-full border border-cyan-400/20"
              animate={{ rotate: -360 }}
              transition={{ duration: 18, repeat: Infinity, ease: 'linear' }}
            />
          </motion.div>

          <motion.h1
            initial={{ opacity: 0, y: 18 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.18 }}
            className="mb-2 text-6xl font-bold tracking-[-3px] text-white"
          >
            VIV
          </motion.h1>

          <motion.p
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ delay: 0.3 }}
            className="mb-8 text-lg tracking-[4px] text-cyan-300"
          >
            VECTOR INTELLIGENCE VAULT
          </motion.p>

          <motion.p
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ delay: 0.42 }}
            className="mb-12 max-w-md text-xl leading-tight text-cyan-100/70"
          >
            Life Management & Navigation System
            <br />
            Know before you need to know.
          </motion.p>

          <div className="w-80">
            <div className="mb-3 h-1 overflow-hidden rounded-full bg-[#1f2937]">
              <motion.div
                className="h-full rounded-full bg-gradient-to-r from-[#7c3aed] via-[#1d4ed8] to-[#00d2b5]"
                initial={{ width: '0%' }}
                animate={{ width: `${progress}%` }}
              />
            </div>
            <div className="flex justify-between text-xs text-cyan-100/60">
              <span>INITIALIZING INTELLIGENCE VAULT</span>
              <span>{Math.floor(progress)}%</span>
            </div>
          </div>

          <motion.p
            initial={{ opacity: 0 }}
            animate={{ opacity: [0.4, 1, 0.4] }}
            transition={{ duration: 2, repeat: Infinity }}
            className="mt-12 text-[10px] tracking-widest text-cyan-100/45"
          >
            BE SMART. BE INFORMED. BE READY.
          </motion.p>
        </div>

        <div className="absolute bottom-8 right-8 font-mono text-xs text-cyan-100/35">v2026.05</div>
      </motion.div>
    </AnimatePresence>
  )
}
