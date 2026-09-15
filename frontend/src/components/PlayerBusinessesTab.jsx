// ─────────────────────────────────────────────────────────────────────────────
// PlayerBusinessesTab · вкладка «Бизнесы игроков».
// Заглушка: раздел пока пустой, наполнение (витрина бизнесов игроков, покупка
// товаров в чужих бизнесах) добавится следующим шагом.
// ─────────────────────────────────────────────────────────────────────────────
import { Handshake } from 'lucide-react'

function PlayerBusinessesTab() {
  return (
    <div className="cars-tab market-tab player-businesses-tab">
      <h2 className="tab-title">
        <Handshake size={22} style={{ verticalAlign: '-4px', marginRight: 8 }} />
        Бизнесы игроков
      </h2>

      <div className="empty-state">
        <div style={{
          display: 'flex', flexDirection: 'column', alignItems: 'center',
          gap: 12, padding: '24px 16px', textAlign: 'center', maxWidth: 480,
          margin: '0 auto',
        }}>
          <div style={{
            width: 84, height: 84, borderRadius: 20,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            background: 'linear-gradient(135deg,#1e40af,#1e3a8a)',
            boxShadow: '0 8px 24px rgba(30,64,175,0.25)',
          }}>
            <Handshake size={40} color="#ffffff" />
          </div>
          <h3 style={{ margin: 0, fontSize: 18 }}>Раздел в разработке</h3>
          <p style={
            { margin: 0, color: 'var(--text-muted, #9ca3af)', lineHeight: 1.5, fontSize: 14 }
          }>
            Здесь скоро появятся бизнесы других игроков, в которых можно будет
            приобретать товары, услуги и активы. Как только наполнение появится,
            карточки бизнесов будут выводиться в этой же вкладке.
          </p>
        </div>
      </div>
    </div>
  )
}

export default PlayerBusinessesTab
