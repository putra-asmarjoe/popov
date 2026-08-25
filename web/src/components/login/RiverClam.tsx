/**
 * RiverClam — ilustrasi SVG kerang sungai untuk scene login sinematik.
 *
 * Dua katup terpisah (class `clam-valve--top` / `clam-valve--bottom`) agar
 * transisi buka-tutup dikendalikan dari CSS berdasarkan `[data-stage]` di
 * ancestor (lihat styles/login-scene.css). Komponen ini stateless murni.
 *
 * Palet adalah artwork internal (cangkang alami zaitun-cokelat matte dengan
 * rim-light biru langit + interior nacre iridescent menyatu ke nuansa logo),
 * bukan token tema — pengecualian sadar karena ini ilustrasi, bukan UI.
 */
export function RiverClam({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 280 210"
      role="img"
      aria-hidden="true"
      className={className}
      focusable="false"
    >
      <defs>
        {/* Cangkang luar — zaitun/cokelat gelap matte */}
        <linearGradient id="rc-shellBottom" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="#514c39" />
          <stop offset="55%" stopColor="#3b3728" />
          <stop offset="100%" stopColor="#26251a" />
        </linearGradient>
        <linearGradient id="rc-shellTop" x1="0.15" y1="0" x2="0.85" y2="1">
          <stop offset="0%" stopColor="#5a5640" />
          <stop offset="45%" stopColor="#413d2c" />
          <stop offset="100%" stopColor="#2c2b1d" />
        </linearGradient>

        {/* Interior nacre — putih mutiara → biru langit pucat → hint violet */}
        <linearGradient id="rc-nacre" x1="0" y1="0" x2="0.9" y2="1">
          <stop offset="0%" stopColor="#fbfbf7" />
          <stop offset="42%" stopColor="#dceffb" />
          <stop offset="78%" stopColor="#dbe7f6" />
          <stop offset="100%" stopColor="#e4dff3" />
        </linearGradient>

        {/* Mutiara kecil */}
        <radialGradient id="rc-pearl" cx="0.35" cy="0.3" r="0.9">
          <stop offset="0%" stopColor="#ffffff" />
          <stop offset="60%" stopColor="#e8f3fc" />
          <stop offset="100%" stopColor="#b9d2e4" />
        </radialGradient>

        {/* Cahaya dari dalam kerang (menyala saat terbuka) */}
        <radialGradient id="rc-inner-glow" cx="0.5" cy="0.45" r="0.6">
          <stop offset="0%" stopColor="#eaf6ff" stopOpacity="0.95" />
          <stop offset="55%" stopColor="#cfe7fa" stopOpacity="0.5" />
          <stop offset="100%" stopColor="#cfe7fa" stopOpacity="0" />
        </radialGradient>
      </defs>

      {/* ===== Katup bawah (mangkuk) ===== */}
      <g className="clam-valve clam-valve--bottom">
        {/* Badan cangkang */}
        <path
          d="M 26 130
             C 34 168, 82 192, 140 194
             C 198 192, 246 168, 254 130
             C 250 138, 210 150, 140 152
             C 70 150, 30 138, 26 130 Z"
          fill="url(#rc-shellBottom)"
        />

        {/* Alur pertumbuhan + sheen biru halus */}
        <path
          d="M 46 152 C 72 174, 106 184, 140 185"
          fill="none" stroke="#22241a" strokeWidth="2" strokeLinecap="round" opacity="0.5"
        />
        <path
          d="M 78 162 C 98 176, 120 181, 140 182"
          fill="none" stroke="#22241a" strokeWidth="1.6" strokeLinecap="round" opacity="0.4"
        />
        <path
          d="M 234 152 C 208 174, 174 184, 140 185"
          fill="none" stroke="#22241a" strokeWidth="2" strokeLinecap="round" opacity="0.5"
        />
        <path
          d="M 40 146 C 70 172, 104 183, 140 184"
          fill="none" stroke="#7ec8f0" strokeWidth="1.4" strokeLinecap="round" opacity="0.14"
        />

        {/* Rim-light biru langit di siluet bawah */}
        <path
          d="M 30 136 C 44 170, 88 188, 140 189 C 192 188, 236 170, 250 136"
          fill="none" stroke="#7ec8f0" strokeWidth="1.7" strokeLinecap="round" opacity="0.32"
        />

        {/* Permukaan dalam nacre (terlihat saat katup atas membuka) */}
        <path
          className="clam-nacre"
          d="M 40 131
             C 60 143, 96 149, 140 150
             C 184 149, 220 143, 240 131
             C 214 121, 178 116, 140 116
             C 102 116, 66 121, 40 131 Z"
          fill="url(#rc-nacre)"
        />
        <ellipse className="clam-nacre" cx="140" cy="133" rx="92" ry="11" fill="#b7cad8" opacity="0.5" />

        {/* Cahaya dalam — opacity dikendalikan CSS saat stage "lit" */}
        <path
          className="clam-nacre-glow"
          d="M 40 131
             C 60 143, 96 149, 140 150
             C 184 149, 220 143, 240 131
             C 214 121, 178 116, 140 116
             C 102 116, 66 121, 40 131 Z"
          fill="url(#rc-inner-glow)"
        />

        {/* Dua mutiara — gumpalan besar + kecil */}
        <circle className="clam-nacre" cx="118" cy="127" r="11" fill="url(#rc-pearl)" />
        <circle className="clam-nacre" cx="161" cy="130" r="7.5" fill="url(#rc-pearl)" />
        <g className="clam-nacre clam-pearl-shine">
          <ellipse cx="113.5" cy="122.5" rx="4.2" ry="2.8" fill="#ffffff" opacity="0.85" />
          <ellipse cx="158.5" cy="126.8" rx="2.8" ry="1.9" fill="#ffffff" opacity="0.85" />
        </g>

        {/* Engsel gelap di kedua ujung */}
        <path d="M 26 128 L 46 123 L 46 133 L 26 134 Z" fill="#1e2117" />
        <path d="M 254 128 L 234 123 L 234 133 L 254 134 Z" fill="#1e2117" />
      </g>

      {/* ===== Katup atas (tutup dome, membuka ke belakang) ===== */}
      <g className="clam-valve clam-valve--top">
        {/* Badan cangkang */}
        <path
          d="M 24 126
             C 30 74, 76 40, 140 38
             C 204 40, 250 74, 256 126
             C 218 132, 180 135, 140 135
             C 100 135, 62 132, 24 126 Z"
          fill="url(#rc-shellTop)"
        />

        {/* Alur pertumbuhan konsentris */}
        <path
          d="M 44 118 C 52 78, 88 52, 140 50"
          fill="none" stroke="#20241a" strokeWidth="2.2" strokeLinecap="round" opacity="0.45"
        />
        <path
          d="M 70 122 C 78 88, 106 64, 140 62"
          fill="none" stroke="#20241a" strokeWidth="1.8" strokeLinecap="round" opacity="0.4"
        />
        <path
          d="M 236 118 C 228 78, 192 52, 140 50"
          fill="none" stroke="#20241a" strokeWidth="2.2" strokeLinecap="round" opacity="0.45"
        />
        <path
          d="M 210 122 C 202 88, 174 64, 140 62"
          fill="none" stroke="#20241a" strokeWidth="1.8" strokeLinecap="round" opacity="0.4"
        />
        {/* Sheen kebiruhan pada dua alur */}
        <path
          d="M 57 120 C 65 83, 97 58, 140 56"
          fill="none" stroke="#7ec8f0" strokeWidth="1.3" strokeLinecap="round" opacity="0.16"
        />
        <path
          d="M 223 120 C 215 83, 183 58, 140 56"
          fill="none" stroke="#7ec8f0" strokeWidth="1.3" strokeLinecap="round" opacity="0.16"
        />

        {/* Bintik periostracum pudar */}
        <ellipse cx="92" cy="82" rx="6" ry="3" fill="#6d6b52" opacity="0.28" transform="rotate(-24 92 82)" />
        <ellipse cx="152" cy="66" rx="5" ry="2.6" fill="#6d6b52" opacity="0.24" transform="rotate(-6 152 66)" />
        <ellipse cx="188" cy="94" rx="6.5" ry="3" fill="#6d6b52" opacity="0.26" transform="rotate(22 188 94)" />
        <ellipse cx="112" cy="108" rx="5.5" ry="2.8" fill="#6d6b52" opacity="0.22" transform="rotate(-12 112 108)" />
        <ellipse cx="206" cy="114" rx="4.5" ry="2.4" fill="#6d6b52" opacity="0.22" transform="rotate(30 206 114)" />

        {/* Tepian dasar gelap (sambungan engsel) */}
        <path
          d="M 26 126 C 64 133, 102 136, 140 136 C 178 136, 216 133, 254 126"
          fill="none" stroke="#171a12" strokeWidth="2.6" strokeLinecap="round" opacity="0.8"
        />

        {/* Bibir nacre tipis di dasar (kelihatan selama animasi buka) */}
        <path
          className="clam-nacre"
          d="M 30 124 C 68 130, 104 133, 140 133 C 176 133, 212 130, 250 124
             C 214 119, 178 117, 140 117 C 102 117, 66 119, 30 124 Z"
          fill="url(#rc-nacre)" opacity="0.9"
        />

        {/* Rim-light biru langit di siluet atas */}
        <path
          d="M 28 118 C 36 72, 80 44, 140 42 C 200 44, 244 72, 252 118"
          fill="none" stroke="#8fd2f7" strokeWidth="1.8" strokeLinecap="round" opacity="0.38"
        />
      </g>
    </svg>
  )
}
