import { ALL_RULES } from '../services/excelExporter';
import { FindingCategory } from '../models/finding';

interface Props {
  onClose: () => void;
}

export default function RulesCatalogModal({ onClose }: Props) {
  // Group rules by category
  const grouped = ALL_RULES.reduce<Record<string, typeof ALL_RULES>>((acc, rule) => {
    const cat = rule.category;
    if (!acc[cat]) acc[cat] = [];
    acc[cat].push(rule);
    return acc;
  }, {});

  const categories = Object.keys(grouped);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50"
      onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}
    >
      <div className="bg-white rounded-xl shadow-2xl w-full max-w-4xl max-h-[85vh] flex flex-col overflow-hidden mx-4">
        {/* Header */}
        <div className="bg-ui-navy px-6 py-4 flex items-center justify-between flex-shrink-0">
          <div>
            <h2 className="text-white font-semibold text-base">Rules Catalog</h2>
            <p className="text-gray-400 text-xs mt-0.5">{ALL_RULES.length} rules across {categories.length} categories</p>
          </div>
          <button
            onClick={onClose}
            className="text-gray-400 hover:text-white transition-colors"
          >
            <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        {/* Body */}
        <div className="overflow-y-auto p-6 space-y-6">
          {categories.map((category) => (
            <div key={category}>
              <h3 className="text-sm font-semibold text-ui-navy mb-2 flex items-center gap-2">
                {category}
                <span className="bg-ui-g100 text-ui-g600 rounded-full px-2 py-0.5 text-[10px] font-bold">
                  {grouped[category].length}
                </span>
              </h3>
              <table className="w-full text-sm border border-ui-g200 rounded-lg overflow-hidden">
                <thead>
                  <tr className="bg-ui-g50">
                    <th className="text-left px-3 py-2 text-xs text-ui-g500 font-medium w-24">Rule ID</th>
                    <th className="text-left px-3 py-2 text-xs text-ui-g500 font-medium">Rule Name</th>
                  </tr>
                </thead>
                <tbody>
                  {grouped[category].map((rule) => (
                    <tr key={rule.rule_id} className="border-t border-ui-g100 hover:bg-ui-g50">
                      <td className="px-3 py-1.5 text-ui-orange font-mono text-xs font-medium">{rule.rule_id}</td>
                      <td className="px-3 py-1.5 text-ui-g700">{rule.rule_name}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
