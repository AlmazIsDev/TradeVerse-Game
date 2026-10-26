import { useState } from 'react'
import { Check, Coins, LockKeyhole, RotateCcw, ShieldAlert, Sparkles, Trophy, Zap } from 'lucide-react'

function Panel({ title, description, children }) {
  return <section className="puzzle-lab-card"><h2>{title}</h2><p>{description}</p>{children}</section>
}

function Result({ text, success = false }) {
  return text ? <div className={`puzzle-lab-result ${success ? 'success' : 'warning'}`}><Check size={15} /> {text}</div> : null
}

function RiskLadder() {
  const [step, setStep] = useState(0)
  const [message, setMessage] = useState('Каждый шаг — новый бросок удачи')
  const [stopped, setStopped] = useState(false)
  const risk = [72, 62, 52, 42, 32]
  const tryNext = () => {
    if (step >= 5 || stopped) return
    if (Math.random() * 100 < risk[step]) {
      const next = step + 1
      setStep(next)
      setMessage(next === 5 ? 'Щит полностью отключён' : `Прорыв успешен · следующий шанс ${risk[next]}%`)
    } else {
      setStopped(true)
      setMessage(`Тревога на уровне ${step + 1} · попытка закончена`)
    }
  }
  const reset = () => { setStep(0); setStopped(false); setMessage('Каждый шаг — новый бросок удачи') }
  return <>
    <div className="risk-ladder">{risk.map((chance, index) => <div key={chance} className={`risk-step ${index < step ? 'passed' : ''} ${index === step && !stopped ? 'current' : ''}`}><span>{index < step ? '✓' : index + 1}</span><small>{chance}%</small></div>)}</div>
    <div className="puzzle-lab-actions"><button className="puzzle-lab-button" onClick={tryNext} disabled={stopped || step === 5}><Zap size={15} /> {step === 5 ? 'Захвачено' : 'Рискнуть ещё'}</button><button className="puzzle-lab-icon-button" onClick={reset} aria-label="Сбросить"><RotateCcw size={16} /></button></div>
    <Result text={message} success={step === 5} />
  </>
}

function Doors() {
  const [round, setRound] = useState(0)
  const [message, setMessage] = useState('Выберите одну дверь')
  const [picked, setPicked] = useState(null)
  const choose = door => {
    if (picked !== null) return
    const lucky = Math.floor(Math.random() * 3)
    setPicked(door)
    setMessage(door === lucky ? 'Доступ найден — повезло' : 'Ложный след — дверь закрылась')
  }
  const reset = () => { setRound(round + 1); setPicked(null); setMessage('Выберите одну дверь') }
  return <>
    <div className="doors-row">{['A', 'B', 'C'].map((door, index) => <button key={door} className={`door ${picked === index ? 'picked' : ''}`} onClick={() => choose(index)} disabled={picked !== null}><span>▣</span><b>{door}</b></button>)}</div>
    <button className="puzzle-lab-button" onClick={reset}><RotateCcw size={15} /> Новая попытка</button><Result text={`${message} · раунд ${round + 1}`} success={picked !== null && message.includes('найден')} />
  </>
}

function AlarmWheel() {
  const [result, setResult] = useState(null)
  const spin = () => setResult(Math.random() < 0.62 ? 'Успех — сигнал погашен' : 'Тревога — защита сработала')
  return <>
    <div className="alarm-wheel"><div className="alarm-wheel-pointer" /><div className="alarm-wheel-face"><span>УСПЕХ</span><span>ТРЕВОГА</span><span>УСПЕХ</span><span>ТРЕВОГА</span><span>БОНУС</span><span>УСПЕХ</span></div></div>
    <button className="puzzle-lab-button" onClick={spin}><Zap size={15} /> Остановить сигнал</button><Result text={result || 'Колесо готово · шанс успеха 62%'} success={result?.startsWith('Успех')} />
  </>
}

function HackSlots() {
  const symbols = ['◆', '✦', '▣', '⬟', '●']
  const [slots, setSlots] = useState(['?', '?', '?'])
  const [message, setMessage] = useState('Три барабана — один шанс')
  const spin = () => {
    const next = Array.from({ length: 3 }, () => symbols[Math.floor(Math.random() * symbols.length)])
    setSlots(next)
    setMessage(next.every(value => value === next[0]) ? 'Тройное совпадение — критический взлом' : next[0] === next[1] || next[1] === next[2] ? 'Частичный доступ — попробуйте ещё' : 'Система отклонила сигнал')
  }
  return <>
    <div className="hack-slots">{slots.map((slot, index) => <div className="hack-slot" key={index}>{slot}</div>)}</div>
    <button className="puzzle-lab-button" onClick={spin}><Coins size={15} /> Запустить барабаны</button><Result text={message} success={message.includes('критический')} />
  </>
}

export default function CityRoofPuzzleLab() {
  return <main className="puzzle-lab puzzle-lab-dark">
    <header className="puzzle-lab-header"><div className="puzzle-lab-kicker"><Sparkles size={16} /> CITY ROOF / LUCK LAB</div><h1>Четыре способа рискнуть</h1><p>Это не логические задачи — только короткие азартные решения. Нажми, испытай удачу и сравни ощущения. WarCoin не списываются.</p></header>
    <div className="puzzle-lab-grid">
      <Panel title="1. Риск-лестница" description="Можно остановиться или идти дальше за полным захватом."><RiskLadder /></Panel>
      <Panel title="2. Три двери" description="За одной дверью доступ, две ведут в ложный след."><Doors /></Panel>
      <Panel title="3. Рулетка тревоги" description="Остановите вращение в безопасной зоне."><AlarmWheel /></Panel>
      <Panel title="4. Слоты взлома" description="Три барабана, редкое совпадение и шанс на бонус."><HackSlots /></Panel>
    </div>
    <footer className="puzzle-lab-footer"><LockKeyhole size={16} /> Тестовая страница · <ShieldAlert size={16} /> игровой баланс не изменяется <Trophy size={16} /></footer>
  </main>
}
