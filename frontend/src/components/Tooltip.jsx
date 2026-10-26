import { useState } from 'react'
import { HelpCircle } from 'lucide-react'

function Tooltip({ text }) {
  const [show, setShow] = useState(false)
  return (
    <span
      className="tooltip-wrapper"
      onMouseEnter={() => setShow(true)}
      onMouseLeave={() => setShow(false)}
      onFocus={() => setShow(true)}
      onBlur={() => setShow(false)}
      tabIndex={0}
      aria-label={text}
    >
      <HelpCircle size={14} className="tooltip-icon" aria-hidden="true" />
      {show && <span className="tooltip-text" role="tooltip">{text}</span>}
    </span>
  )
}

export default Tooltip
