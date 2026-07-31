import { useState, useEffect } from 'react';
import { chores } from '../api';
import { useAuth } from '../context/AuthContext';

export default function Chores() {
  const { household } = useAuth();
  const [list, setList] = useState([]);
  const [leaderboard, setLeaderboard] = useState([]);
  const [message, setMessage] = useState('');

  const fetchData = async () => {
    if (!household) return;
    try {
      const [c, lb] = await Promise.all([
        chores.list(household.household_id),
        chores.leaderboard(household.household_id),
      ]);
      setList(c);
      setLeaderboard(lb);
    } catch {}
  };

  useEffect(() => { fetchData(); }, [household]);

  const handleComplete = async (choreId) => {
    setMessage('');
    try {
      const result = await chores.complete(household.household_id, choreId);
      setMessage(`${result.chore_name} completed! +${result.points} pts for you, -${result.points} for others`);
      fetchData();
    } catch (err) {
      setMessage(err.message);
    }
  };

  const handleAdd = async (choreName, chorePoints) => {
    setMessage('');
    try {
      await chores.create(household.household_id, { name: choreName, points: chorePoints });
      fetchData();
    } catch (err) {
      setMessage(err.message);
    }
  };

  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
      <div className="space-y-4">
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-bold">Chores</h2>
        </div>

        {message && <p className="text-green-600 text-sm font-medium">{message}</p>}

        <AddChoreForm onAdd={handleAdd} />

        <table className="w-full border border-gray-200 rounded-lg overflow-hidden">
          <thead>
            <tr className="bg-gray-50">
              <th className="text-left text-xs font-semibold text-gray-500 px-4 py-2">Chore</th>
              <th className="text-left text-xs font-semibold text-gray-500 px-4 py-2">Points</th>
              <th className="text-left text-xs font-semibold text-gray-500 px-4 py-2">Done</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {list.length === 0 ? (
              <tr><td colSpan={3} className="text-center text-gray-500 text-sm py-8">No chores yet.</td></tr>
            ) : (
              list.map(chore => (
                <tr key={chore.id} className="hover:bg-gray-50">
                  <td className="px-4 py-3 text-sm font-medium">{chore.name}</td>
                  <td className="px-4 py-3 text-sm text-gray-600">{chore.points}</td>
                  <td className="px-4 py-3">
                    <button onClick={() => handleComplete(chore.id)}
                      className="text-xs bg-green-600 text-white px-3 py-1.5 rounded hover:bg-green-700">
                      Done
                    </button>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      <div>
        <h2 className="text-lg font-bold mb-4">Leaderboard</h2>
        {leaderboard.length === 0 ? (
          <p className="text-gray-500 text-sm">No completions yet.</p>
        ) : (
          <div className="space-y-2">
            {leaderboard.map((entry, i) => (
              <div key={entry.member_id} className="bg-white border border-gray-200 rounded-lg p-4 flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <span className={`w-7 h-7 rounded-full flex items-center justify-center text-sm font-bold text-white ${
                    i === 0 ? 'bg-yellow-500' : i === 1 ? 'bg-gray-400' : i === 2 ? 'bg-amber-700' : 'bg-gray-300'
                  }`}>
                    {i + 1}
                  </span>
                  <span className="font-medium text-sm">{entry.name}</span>
                </div>
                <span className={`text-sm font-bold ${entry.net >= 0 ? 'text-green-600' : 'text-red-600'}`}>
                  {entry.net >= 0 ? '+' : ''}{entry.net}
                </span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function AddChoreForm({ onAdd }) {
  const [show, setShow] = useState(false);
  const [name, setName] = useState('');
  const [points, setPoints] = useState('');

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!name || !points) return;
    await onAdd(name, parseInt(points, 10));
    setName('');
    setPoints('');
    setShow(false);
  };

  return (
    <>
      <button onClick={() => setShow(!show)} className="text-xs text-blue-600 hover:underline">
        {show ? 'Cancel' : 'Add chore'}
      </button>
      {show && (
        <form onSubmit={handleSubmit} className="flex gap-2 items-center bg-gray-50 border border-gray-200 rounded-lg p-3">
          <input type="text" placeholder="Chore name" value={name} onChange={e => setName(e.target.value)} required
            className="flex-1 border border-gray-300 rounded px-3 py-1.5 text-sm" />
          <select value={points} onChange={e => setPoints(e.target.value)} required
            className="border border-gray-300 rounded px-3 py-1.5 text-sm">
            <option value="">Points</option>
            <option value="50">50</option>
            <option value="100">100</option>
            <option value="150">150</option>
            <option value="200">200</option>
          </select>
          <button type="submit" className="bg-blue-600 text-white text-sm px-3 py-1.5 rounded hover:bg-blue-700">
            Add
          </button>
        </form>
      )}
    </>
  );
}
