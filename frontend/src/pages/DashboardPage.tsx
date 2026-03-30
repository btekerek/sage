import { useNavigate } from 'react-router-dom'

export default function DashboardPage() {
  const navigate = useNavigate()

  return (
    <div className="min-h-screen bg-gray-50">
      <nav className="bg-white shadow px-6 py-4 flex justify-between items-center">
        <h1 className="text-xl font-bold">SAGE</h1>
        <div className="flex gap-4">
          <button
            onClick={() => navigate('/pos')}
            className="text-sm bg-blue-600 text-white px-4 py-2 rounded hover:bg-blue-700"
          >
            Open POS
          </button>
        </div>
      </nav>
      <div className="p-8">
        <h2 className="text-2xl font-bold mb-6">Management Dashboard</h2>
        <p className="text-gray-500">KPIs, invoice queue, and replenishment coming soon.</p>
      </div>
    </div>
  )
}