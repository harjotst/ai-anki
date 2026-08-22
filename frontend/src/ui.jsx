// Shared primitives: icons, toasts, sheets, error and loading states.
// Icons are inline stroke SVGs on a 24px grid — no emoji, no icon font.
import React, { createContext, useCallback, useContext, useRef, useState } from "react";

const PATHS = {
  plus: <path d="M12 5v14M5 12h14" />,
  minus: <path d="M5 12h14" />,
  x: <path d="M6 6l12 12M18 6L6 18" />,
  chevR: <path d="M9 6l6 6-6 6" />,
  chevL: <path d="M15 6l-6 6 6 6" />,
  chevD: <path d="M6 9l6 6 6-6" />,
  check: <path d="M5 12.5l4.5 4.5L19 7.5" />,
  today: (
    <>
      <rect x="4" y="5" width="16" height="16" rx="2.5" />
      <path d="M4 10h16M8 3v4M16 3v4" />
      <path d="M9 15.5l2 2 4-4" />
    </>
  ),
  decks: (
    <>
      <path d="M12 3l9 5-9 5-9-5 9-5z" />
      <path d="M3 13l9 5 9-5" />
    </>
  ),
  board: <path d="M5 20v-8M12 20V5M19 20v-5" />,
  you: (
    <>
      <circle cx="12" cy="8.5" r="3.5" />
      <path d="M5 20c1.4-3.2 4-4.8 7-4.8s5.6 1.6 7 4.8" />
    </>
  ),
  dots: (
    <>
      <circle cx="5" cy="12" r="1.1" fill="currentColor" stroke="none" />
      <circle cx="12" cy="12" r="1.1" fill="currentColor" stroke="none" />
      <circle cx="19" cy="12" r="1.1" fill="currentColor" stroke="none" />
    </>
  ),
  share: (
    <>
      <circle cx="6" cy="12" r="2.4" />
      <circle cx="17.5" cy="6" r="2.4" />
      <circle cx="17.5" cy="18" r="2.4" />
      <path d="M8.2 10.8l7-3.6M8.2 13.2l7 3.6" />
    </>
  ),
  download: (
    <>
      <path d="M12 4v11M7.5 10.5L12 15l4.5-4.5" />
      <path d="M5 19.5h14" />
    </>
  ),
  doc: (
    <>
      <path d="M7 3.5h7l4 4V20a1.5 1.5 0 0 1-1.5 1.5h-9A1.5 1.5 0 0 1 6 20V5a1.5 1.5 0 0 1 1-1.4z" />
      <path d="M12 11v6M9 14h6" />
    </>
  ),
  copy: (
    <>
      <rect x="9" y="9" width="11" height="11" rx="2" />
      <path d="M5 15H4.5A1.5 1.5 0 0 1 3 13.5v-9A1.5 1.5 0 0 1 4.5 3h9A1.5 1.5 0 0 1 15 4.5V5" />
    </>
  ),
  edit: <path d="M4 20l1-4L17.5 3.5a2.1 2.1 0 0 1 3 3L8 19l-4 1z" />,
  search: (
    <>
      <circle cx="11" cy="11" r="6.5" />
      <path d="M20 20l-4.2-4.2" />
    </>
  ),
  undo: <path d="M8 5L3.5 9.5 8 14M4 9.5h10a6 6 0 0 1 0 12h-3" />,
  info: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 11v5M12 7.5v.5" />
    </>
  ),
};

export function Icon({ name, size = 22, style }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      style={{ flexShrink: 0, ...style }}
    >
      {PATHS[name]}
    </svg>
  );
}

// --- toasts ----------------------------------------------------------------

const ToastContext = createContext(() => {});
export const useToast = () => useContext(ToastContext);

export function ToastHost({ children }) {
  const [toasts, setToasts] = useState([]);
  const nextId = useRef(0);

  const push = useCallback((message, { action, onAction, ttl = 4000 } = {}) => {
    const id = nextId.current++;
    setToasts((current) => [...current, { id, message, action, onAction }]);
    window.setTimeout(
      () => setToasts((current) => current.filter((t) => t.id !== id)),
      ttl
    );
  }, []);

  return (
    <ToastContext.Provider value={push}>
      {children}
      <div className="toast-host">
        {toasts.map((toast) => (
          <div key={toast.id} className="toast">
            <span>{toast.message}</span>
            {toast.action && (
              <button
                onClick={() => {
                  toast.onAction?.();
                  setToasts((current) => current.filter((t) => t.id !== toast.id));
                }}
              >
                {toast.action}
              </button>
            )}
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

// --- states ----------------------------------------------------------------

export function ErrorCard({ message, onRetry }) {
  return (
    <div className="error-card">
      <span className="sec" style={{ flex: 1, color: "var(--text)" }}>{message}</span>
      {onRetry && (
        <button className="btn btn-ghost btn-small" onClick={onRetry}>
          Retry
        </button>
      )}
    </div>
  );
}

export function Skeleton({ h = 56, w = "100%", r = "var(--radius-md)" }) {
  return <div className="skeleton" style={{ height: h, width: w, borderRadius: r }} />;
}

export function Sheet({ onClose, children }) {
  return (
    <div
      className="sheet-scrim"
      onClick={(e) => e.target === e.currentTarget && onClose()}
    >
      <div className="sheet">{children}</div>
    </div>
  );
}

export function Seg({ options, value, onChange, style }) {
  return (
    <div className="seg" style={style}>
      {options.map(([key, label]) => (
        <button
          key={key}
          className={key === value ? "on" : ""}
          onClick={() => onChange(key)}
        >
          {label}
        </button>
      ))}
    </div>
  );
}

/** The one renderer for card text, used by study, review and the browser —
 *  judging a cloze card from its markup is judging the wrong thing, and two
 *  renderers is how front and back drift apart. */
export function CardText({ text, size = 18 }) {
  return (
    <div style={{ fontSize: size, lineHeight: 1.5, whiteSpace: "pre-wrap" }}>
      {text}
    </div>
  );
}
