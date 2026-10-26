import { useEffect, useMemo, useState } from 'react'
import { ArrowRight, Check, LockKeyhole, RotateCcw, ShieldAlert, Sparkles } from 'lucide-react'

const COLORS = ['#ef4444', '#f97316', '#eab308', '#22c55e', '#06b6d4', '#6366f1']
const ICONS = ['◆', '●', '▲', '■', '✦', '⬟']

function Panel({ title, description, children }) {
  return (
    <section className="puzzle-lab-card">
      <div className="puzzle-lab-card-head">
        <div>
          <h2>{title}</h2>
          <p>{description}</p>
        </div>
      </div>
      {children}
    </section>
  )
}

function MastermindDemo() {
  const secret = [2, 4, 1, 5]
  const [guess, setGuess] = useState([0, 0, 0, 0])
  const [message, setMessage] = useState('')
  const submit = () => {
    const exact = guess.filter((value, index) => value === secret[index]).length
    setMessage(exact === secret.length ? 'Взломано' : `Совпадений по позиции: ${exact}`)
  }
  return (
    <>
      <div className="puzzle-lab-pegs">
        {guess.map((value, index) => <button key={index} className="puzzle-lab-peg" style={{ background: COLORS[value] }} onClick={() => setGuess(g => g.map((v, i) => i === index ? (v + 1) % COLORS.length : v))} />)}
      </div>
      <button className="puzzle-lab-button" onClick={submit}>Проверить код</button>
      <DemoResult text={message} />
    </>
  )
}

function NetworkDemo() {
  const base = useMemo(() => ['┌', '┐', '└', '┘', '─', '│', '┌', '┘', '└', '─', '│', '┐', '└', '─', '┌', '┘'], [])
  const [turns, setTurns] = useState(Array(16).fill(0))
  const [message, setMessage] = useState('')
  const reset = () => { setTurns(Array(16).fill(0)); setMessage('') }
  const rotate = index => setTurns(values => values.map((value, i) => i === index ? (value + 1) % 4 : value))
  return (
    <>
      <div className="network-board">
        {base.map((tile, index) => <button key={index} className="network-tile" onClick={() => rotate(index)} style={{ transform: `rotate(${turns[index] * 90}deg)` }}>{tile}</button>)}
      </div>
      <div className="puzzle-lab-actions">
        <button className="puzzle-lab-button" onClick={() => setMessage('Маршрут подключён')}>Подключить маршрут <ArrowRight size={15} /></button>
        <button className="puzzle-lab-icon-button" onClick={reset} aria-label="Сбросить"><RotateCcw size={16} /></button>
      </div>
      <DemoResult text={message} />
    </>
  )
}

function MemoryDemo() {
  const [sequence, setSequence] = useState([1, 4, 2])
  const [shown, setShown] = useState(true)
  const [input, setInput] = useState([])
  const [message, setMessage] = useState('Запомните последовательность')
  useEffect(() => {
    const timer = setTimeout(() => { setShown(false); setMessage('Повторите её') }, 1400)
    return () => clearTimeout(timer)
  }, [sequence])
  const click = index => {
    if (shown) return
    const next = [...input, index]
    setInput(next)
    if (next.length === sequence.length) {
      setMessage(next.every((value, i) => value === sequence[i]) ? 'Взломано' : 'Ошибка — попробуйте ещё раз')
    }
  }
  const restart = () => {
    setSequence(Array.from({ length: 3 }, () => Math.floor(Math.random() * 6)))
    setInput([])
    setShown(true)
    setMessage('Запомните последовательность')
  }
  return (
    <>
      <div className="memory-status">{message}</div>
      <div className="memory-grid">
        {ICONS.map((icon, index) => <button key={index} className={`memory-cell ${shown && sequence.includes(index) ? 'lit' : ''}`} onClick={() => click(index)}>{icon}</button>)}
      </div>
      <button className="puzzle-lab-button" onClick={restart}>Новая последовательность</button>
    </>
  )
}

function SafePathDemo() {
  const path = [0, 1, 5, 9, 10, 14, 15]
  const [current, setCurrent] = useState(0)
  const [message, setMessage] = useState('Начните со светлой клетки')
  const move = index => {
    if (index !== path[current + 1]) {
      setMessage('Сработала ловушка — вернитесь на старт')
      setCurrent(0)
      return
    }
    const next = current + 1
    setCurrent(next)
    setMessage(next === path.length - 1 ? 'Щит отключён' : 'Путь найден, продолжайте')
  }
  return (
    <>
      <div className="path-grid">
        {Array.from({ length: 16 }, (_, index) => <button key={index} className={`path-cell ${index === path[current] ? 'current' : ''} ${index === 0 ? 'start' : ''}`} onClick={() => move(index)}>{index === 0 ? 'ВХОД' : index === 15 ? 'ВЫХОД' : ''}</button>)}
      </div>
      <DemoResult text={message} />
    </>
  )
}

function DemoResult({ text }) {
  return text ? <div className="puzzle-lab-result"><Check size={15} /> {text}</div> : null
}

export default function CityRoofPuzzleLab() {
  return (
    <main className="puzzle-lab">
      <header className="puzzle-lab-header">
        <div className="puzzle-lab-kicker"><Sparkles size={16} /> CITY ROOF / ПРОТОТИПЫ</div>
        <h1>Как взламывать защиту зданий?</h1>
        <p>Четыре варианта мини-игры на одной странице. Все работают локально и не списывают WarCoin.</p>
      </header>
      <div className="puzzle-lab-grid">
        <Panel title="1. Цветовой код" description="Текущая механика Mastermind — для сравнения."><MastermindDemo /></Panel>
        <Panel title="2. Взлом сети" description="Поверните узлы и соберите маршрут от входа к выходу."><NetworkDemo /></Panel>
        <Panel title="3. Сигнальная память" description="Запомните последовательность и повторите её после вспышки."><MemoryDemo /></Panel>
        <Panel title="4. Безопасный маршрут" description="Выберите клетки и пройдите через защитную сетку."><SafePathDemo /></Panel>
      </div>
      <footer className="puzzle-lab-footer"><LockKeyhole size={16} /> Тестовая страница · <ShieldAlert size={16} /> данные игры не изменяются</footer>
    </main>
  )
}
