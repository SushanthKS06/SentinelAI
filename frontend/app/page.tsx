'use client';

import React, { useState, useEffect } from 'react';
import { 
  LineChart, 
  Line, 
  AreaChart, 
  Area, 
  XAxis, 
  YAxis, 
  CartesianGrid, 
  Tooltip, 
  ResponsiveContainer,
  BarChart,
  Bar,
  PieChart,
  Pie,
  Cell
} from 'recharts';
import { 
  AlertTriangle, 
  Activity, 
  Server, 
  Zap, 
  Clock, 
  CheckCircle, 
  XCircle,
  TrendingUp,
  TrendingDown,
  Bell,
  Search,
  Settings,
  User,
  Menu,
  X,
  ChevronRight,
  AlertCircle,
  Terminal,
  GitBranch,
  BarChart3,
  Cpu,
  HardDrive,
  Network,
  Database
} from 'lucide-react';
import { cn, formatRelativeTime, getSeverityColor, getStatusColor } from '@/lib/utils';

// Types
interface Incident {
  id: string;
  title: string;
  severity: 'critical' | 'high' | 'medium' | 'low' | 'info';
  status: 'open' | 'investigating' | 'identified' | 'monitoring' | 'resolved';
  service: string;
  startedAt: string;
  ttd?: number;
  ttr?: number;
}

interface Metric {
  name: string;
  value: number;
  unit: string;
  trend: 'up' | 'down' | 'stable';
  change: number;
}

interface Alert {
  id: string;
  name: string;
  severity: string;
  status: string;
  service: string;
  firedAt: string;
}

interface ServiceHealth {
  name: string;
  status: 'healthy' | 'degraded' | 'down';
  latency: number;
  errorRate: number;
  requests: number;
}

// Mock data
const mockIncidents: Incident[] = [
  {
    id: 'inc-001',
    title: 'High CPU usage on payment-service',
    severity: 'critical',
    status: 'investigating',
    service: 'payment-service',
    startedAt: new Date(Date.now() - 15 * 60000).toISOString(),
    ttd: 2,
  },
  {
    id: 'inc-002',
    title: 'Database connection pool exhausted',
    severity: 'high',
    status: 'open',
    service: 'user-service',
    startedAt: new Date(Date.now() - 5 * 60000).toISOString(),
  },
  {
    id: 'inc-003',
    title: 'Elevated latency in checkout flow',
    severity: 'medium',
    status: 'monitoring',
    service: 'checkout-service',
    startedAt: new Date(Date.now() - 45 * 60000).toISOString(),
    ttd: 5,
    ttr: 20,
  },
  {
    id: 'inc-004',
    title: 'Memory leak detected in cache-service',
    severity: 'high',
    status: 'identified',
    service: 'cache-service',
    startedAt: new Date(Date.now() - 30 * 60000).toISOString(),
  },
];

const mockMetrics: Metric[] = [
  { name: 'CPU Usage', value: 72, unit: '%', trend: 'up', change: 12 },
  { name: 'Memory', value: 4.2, unit: 'GB', trend: 'up', change: 8 },
  { name: 'Latency', value: 145, unit: 'ms', trend: 'down', change: -5 },
  { name: 'Error Rate', value: 0.8, unit: '%', trend: 'up', change: 0.3 },
  { name: 'Requests', value: 12500, unit: 'rpm', trend: 'stable', change: 0 },
];

const mockAlerts: Alert[] = [
  { id: 'alert-001', name: 'HighErrorRate', severity: 'critical', status: 'firing', service: 'payment-service', firedAt: new Date(Date.now() - 10 * 60000).toISOString() },
  { id: 'alert-002', name: 'DiskSpaceLow', severity: 'warning', status: 'firing', service: 'database', firedAt: new Date(Date.now() - 30 * 60000).toISOString() },
  { id: 'alert-003', name: 'HighLatency', severity: 'warning', status: 'firing', service: 'api-gateway', firedAt: new Date(Date.now() - 15 * 60000).toISOString() },
];

const mockServices: ServiceHealth[] = [
  { name: 'api-gateway', status: 'healthy', latency: 45, errorRate: 0.1, requests: 5000 },
  { name: 'payment-service', status: 'degraded', latency: 230, errorRate: 2.5, requests: 1200 },
  { name: 'user-service', status: 'healthy', latency: 35, errorRate: 0.05, requests: 3000 },
  { name: 'checkout-service', status: 'healthy', latency: 120, errorRate: 0.2, requests: 800 },
  { name: 'notification-service', status: 'healthy', latency: 25, errorRate: 0.01, requests: 1500 },
  { name: 'database', status: 'healthy', latency: 15, errorRate: 0.0, requests: 10000 },
];

const cpuData = [
  { time: '10:00', value: 45 },
  { time: '10:05', value: 52 },
  { time: '10:10', value: 48 },
  { time: '10:15', value: 61 },
  { time: '10:20', value: 58 },
  { time: '10:25', value: 72 },
  { time: '10:30', value: 68 },
  { time: '10:35', value: 75 },
  { time: '10:40', value: 82 },
  { time: '10:45', value: 78 },
];

const severityData = [
  { name: 'Critical', value: 3, color: '#ef4444' },
  { name: 'High', value: 5, color: '#f97316' },
  { name: 'Medium', value: 8, color: '#eab308' },
  { name: 'Low', value: 12, color: '#22c55e' },
];

// Components
function Header() {
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);

  return (
    <header className="sticky top-0 z-50 w-full border-b border-border bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60">
      <div className="container flex h-14 items-center">
        <div className="flex items-center gap-2">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary">
            <Zap className="h-5 w-5 text-primary-foreground" />
          </div>
          <span className="font-bold text-lg">SentinelAI</span>
        </div>
        
        <nav className="hidden md:flex items-center gap-6 ml-8">
          <a href="#" className="text-sm font-medium text-foreground">Dashboard</a>
          <a href="#" className="text-sm font-medium text-muted-foreground hover:text-foreground">Incidents</a>
          <a href="#" className="text-sm font-medium text-muted-foreground hover:text-foreground">Alerts</a>
          <a href="#" className="text-sm font-medium text-muted-foreground hover:text-foreground">Services</a>
          <a href="#" className="text-sm font-medium text-muted-foreground hover:text-foreground">Analytics</a>
          <a href="#" className="text-sm font-medium text-muted-foreground hover:text-foreground">AI Investigation</a>
        </nav>

        <div className="flex items-center gap-4 ml-auto">
          <div className="hidden md:flex items-center gap-2 px-3 py-1.5 rounded-md bg-muted">
            <Search className="h-4 w-4 text-muted-foreground" />
            <input 
              type="text" 
              placeholder="Search..." 
              className="bg-transparent border-none outline-none text-sm w-48"
            />
            <kbd className="text-xs text-muted-foreground">⌘K</kbd>
          </div>
          
          <button className="relative p-2 rounded-md hover:bg-muted">
            <Bell className="h-5 w-5" />
            <span className="absolute top-1 right-1 h-2 w-2 rounded-full bg-red-500"></span>
          </button>
          
          <button className="p-2 rounded-md hover:bg-muted">
            <Settings className="h-5 w-5" />
          </button>
          
          <button className="p-2 rounded-md hover:bg-muted">
            <User className="h-5 w-5" />
          </button>

          <button 
            className="md:hidden p-2 rounded-md hover:bg-muted"
            onClick={() => setMobileMenuOpen(!mobileMenuOpen)}
          >
            {mobileMenuOpen ? <X className="h-5 w-5" /> : <Menu className="h-5 w-5" />}
          </button>
        </div>
      </div>
    </header>
  );
}

function MetricCard({ metric }: { metric: Metric }) {
  return (
    <div className="rounded-lg border border-border bg-card p-4">
      <div className="flex items-center justify-between">
        <span className="text-sm text-muted-foreground">{metric.name}</span>
        {metric.trend === 'up' ? (
          <TrendingUp className="h-4 w-4 text-green-500" />
        ) : metric.trend === 'down' ? (
          <TrendingDown className="h-4 w-4 text-red-500" />
        ) : (
          <Activity className="h-4 w-4 text-muted-foreground" />
        )}
      </div>
      <div className="mt-2 flex items-baseline gap-1">
        <span className="text-2xl font-bold">{metric.value}</span>
        <span className="text-sm text-muted-foreground">{metric.unit}</span>
      </div>
      <div className="mt-1 text-xs text-muted-foreground">
        <span className={metric.change > 0 ? 'text-red-500' : metric.change < 0 ? 'text-green-500' : ''}>
          {metric.change > 0 ? '+' : ''}{metric.change}
        </span>
        {' '}from last hour
      </div>
    </div>
  );
}

function IncidentCard({ incident }: { incident: Incident }) {
  const severityColors = {
    critical: 'bg-red-500',
    high: 'bg-orange-500',
    medium: 'bg-yellow-500',
    low: 'bg-green-500',
    info: 'bg-blue-500',
  };

  const statusColors = {
    open: 'text-red-500',
    investigating: 'text-yellow-500',
    identified: 'text-orange-500',
    monitoring: 'text-blue-500',
    resolved: 'text-green-500',
  };

  return (
    <div className="flex items-start gap-4 p-4 rounded-lg border border-border hover:bg-muted/50 transition-colors cursor-pointer">
      <div className={cn("w-2 h-2 rounded-full mt-2", severityColors[incident.severity])} />
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <span className="font-medium truncate">{incident.title}</span>
          <span className={cn("text-xs px-2 py-0.5 rounded-full", severityColors[incident.severity], "text-white")}>
            {incident.severity}
          </span>
        </div>
        <div className="mt-1 flex items-center gap-4 text-xs text-muted-foreground">
          <span>{incident.service}</span>
          <span>{formatRelativeTime(incident.startedAt)}</span>
          {incident.ttd && <span>TTD: {incident.ttd}m</span>}
          {incident.ttr && <span>TTR: {incident.ttr}m</span>}
        </div>
      </div>
      <span className={cn("text-sm font-medium", statusColors[incident.status])}>
        {incident.status}
      </span>
    </div>
  );
}

function ServiceStatus({ service }: { service: ServiceHealth }) {
  const statusColors = {
    healthy: 'bg-green-500',
    degraded: 'bg-yellow-500',
    down: 'bg-red-500',
  };

  return (
    <div className="flex items-center justify-between p-3 rounded-lg border border-border">
      <div className="flex items-center gap-3">
        <div className={cn("w-2 h-2 rounded-full", statusColors[service.status])} />
        <span className="font-medium">{service.name}</span>
      </div>
      <div className="flex items-center gap-6 text-xs text-muted-foreground">
        <span>{service.latency}ms</span>
        <span>{service.errorRate}%</span>
        <span>{service.requests.toLocaleString()}/min</span>
      </div>
    </div>
  );
}

function AlertItem({ alert }: { alert: Alert }) {
  const severityColors = {
    critical: 'text-red-500',
    warning: 'text-yellow-500',
    info: 'text-blue-500',
  };

  return (
    <div className="flex items-center gap-3 p-3 rounded-lg border border-border">
      <AlertCircle className={cn("h-4 w-4", severityColors[alert.severity as keyof typeof severityColors] || severityColors.info)} />
      <div className="flex-1 min-w-0">
        <span className="text-sm font-medium">{alert.name}</span>
        <span className="text-xs text-muted-foreground ml-2">{alert.service}</span>
      </div>
      <span className="text-xs text-muted-foreground">{formatRelativeTime(alert.firedAt)}</span>
    </div>
  );
}

function Sidebar() {
  return (
    <aside className="hidden lg:block w-64 border-r border-border p-4">
      <div className="space-y-4">
        <div>
          <h3 className="text-sm font-semibold mb-2">Quick Actions</h3>
          <div className="space-y-1">
            <button className="w-full flex items-center gap-2 px-3 py-2 text-sm rounded-md hover:bg-muted text-left">
              <Terminal className="h-4 w-4" />
              AI Investigation
            </button>
            <button className="w-full flex items-center gap-2 px-3 py-2 text-sm rounded-md hover:bg-muted text-left">
              <GitBranch className="h-4 w-4" />
              Deployments
            </button>
            <button className="w-full flex items-center gap-2 px-3 py-2 text-sm rounded-md hover:bg-muted text-left">
              <BarChart3 className="h-4 w-4" />
              View Analytics
            </button>
          </div>
        </div>

        <div>
          <h3 className="text-sm font-semibold mb-2">System Status</h3>
          <div className="space-y-2">
            <div className="flex items-center justify-between text-sm">
              <div className="flex items-center gap-2">
                <Cpu className="h-4 w-4" />
                <span>CPU</span>
              </div>
              <span className="text-green-500">72%</span>
            </div>
            <div className="flex items-center justify-between text-sm">
              <div className="flex items-center gap-2">
                <HardDrive className="h-4 w-4" />
                <span>Memory</span>
              </div>
              <span className="text-yellow-500">84%</span>
            </div>
            <div className="flex items-center justify-between text-sm">
              <div className="flex items-center gap-2">
                <Database className="h-4 w-4" />
                <span>Database</span>
              </div>
              <span className="text-green-500">Healthy</span>
            </div>
            <div className="flex items-center justify-between text-sm">
              <div className="flex items-center gap-2">
                <Network className="h-4 w-4" />
                <span>Network</span>
              </div>
              <span className="text-green-500">Normal</span>
            </div>
          </div>
        </div>

        <div>
          <h3 className="text-sm font-semibold mb-2">Active Alerts</h3>
          <div className="space-y-1">
            {mockAlerts.slice(0, 3).map(alert => (
              <AlertItem key={alert.id} alert={alert} />
            ))}
          </div>
        </div>
      </div>
    </aside>
  );
}

function MainContent() {
  return (
    <main className="flex-1 p-6 space-y-6">
      {/* Metrics Row */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-5 gap-4">
        {mockMetrics.map((metric) => (
          <MetricCard key={metric.name} metric={metric} />
        ))}
      </div>

      {/* Charts Row */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* CPU Chart */}
        <div className="lg:col-span-2 rounded-lg border border-border bg-card p-4">
          <div className="flex items-center justify-between mb-4">
            <h3 className="font-semibold">CPU Usage</h3>
            <select className="text-sm border border-border rounded-md px-2 py-1 bg-background">
              <option>Last 1 hour</option>
              <option>Last 6 hours</option>
              <option>Last 24 hours</option>
            </select>
          </div>
          <div className="h-64">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={cpuData}>
                <defs>
                  <linearGradient id="cpuGradient" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#3b82f6" stopOpacity={0.3}/>
                    <stop offset="95%" stopColor="#3b82f6" stopOpacity={0}/>
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
                <XAxis dataKey="time" stroke="hsl(var(--muted-foreground))" fontSize={12} />
                <YAxis stroke="hsl(var(--muted-foreground))" fontSize={12} />
                <Tooltip 
                  contentStyle={{ 
                    backgroundColor: 'hsl(var(--card))', 
                    border: '1px solid hsl(var(--border))',
                    borderRadius: '8px'
                  }}
                />
                <Area 
                  type="monotone" 
                  dataKey="value" 
                  stroke="#3b82f6" 
                  fillOpacity={1} 
                  fill="url(#cpuGradient)" 
                />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </div>

        {/* Severity Distribution */}
        <div className="rounded-lg border border-border bg-card p-4">
          <h3 className="font-semibold mb-4">Incidents by Severity</h3>
          <div className="h-64">
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                <Pie
                  data={severityData}
                  cx="50%"
                  cy="50%"
                  innerRadius={60}
                  outerRadius={80}
                  paddingAngle={5}
                  dataKey="value"
                >
                  {severityData.map((entry, index) => (
                    <Cell key={`cell-${index}`} fill={entry.color} />
                  ))}
                </Pie>
                <Tooltip 
                  contentStyle={{ 
                    backgroundColor: 'hsl(var(--card))', 
                    border: '1px solid hsl(var(--border))',
                    borderRadius: '8px'
                  }}
                />
              </PieChart>
            </ResponsiveContainer>
          </div>
          <div className="flex flex-wrap justify-center gap-3 mt-2">
            {severityData.map((item) => (
              <div key={item.name} className="flex items-center gap-1 text-xs">
                <div className="w-2 h-2 rounded-full" style={{ backgroundColor: item.color }} />
                <span>{item.name}</span>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Incidents and Services Row */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Active Incidents */}
        <div className="rounded-lg border border-border bg-card">
          <div className="flex items-center justify-between p-4 border-b border-border">
            <h3 className="font-semibold">Active Incidents</h3>
            <button className="text-sm text-primary hover:underline">View all</button>
          </div>
          <div className="p-4 space-y-2">
            {mockIncidents.map((incident) => (
              <IncidentCard key={incident.id} incident={incident} />
            ))}
          </div>
        </div>

        {/* Service Health */}
        <div className="rounded-lg border border-border bg-card">
          <div className="flex items-center justify-between p-4 border-b border-border">
            <h3 className="font-semibold">Service Health</h3>
            <button className="text-sm text-primary hover:underline">View all</button>
          </div>
          <div className="p-4 space-y-2">
            {mockServices.map((service) => (
              <ServiceStatus key={service.name} service={service} />
            ))}
          </div>
        </div>
      </div>

      {/* AI Investigation Section */}
      <div className="rounded-lg border border-border bg-card p-6">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-primary/10">
              <Zap className="h-5 w-5 text-primary" />
            </div>
            <div>
              <h3 className="font-semibold">AI Investigation Console</h3>
              <p className="text-sm text-muted-foreground">Run AI-powered root cause analysis</p>
            </div>
          </div>
          <button className="px-4 py-2 bg-primary text-primary-foreground rounded-md hover:bg-primary/90">
            New Investigation
          </button>
        </div>
        
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mt-6">
          <button className="p-4 rounded-lg border border-border hover:bg-muted transition-colors text-left">
            <div className="flex items-center gap-2 mb-2">
              <Terminal className="h-4 w-4" />
              <span className="font-medium">Log Analysis</span>
            </div>
            <p className="text-xs text-muted-foreground">Analyze logs for error patterns</p>
          </button>
          <button className="p-4 rounded-lg border border-border hover:bg-muted transition-colors text-left">
            <div className="flex items-center gap-2 mb-2">
              <Activity className="h-4 w-4" />
              <span className="font-medium">Metrics Analysis</span>
            </div>
            <p className="text-xs text-muted-foreground">Detect anomalies in metrics</p>
          </button>
          <button className="p-4 rounded-lg border border-border hover:bg-muted transition-colors text-left">
            <div className="flex items-center gap-2 mb-2">
              <GitBranch className="h-4 w-4" />
              <span className="font-medium">Deployment Correlation</span>
            </div>
            <p className="text-xs text-muted-foreground">Correlate incidents with deployments</p>
          </button>
        </div>
      </div>
    </main>
  );
}

export default function Dashboard() {
  return (
    <div className="min-h-screen bg-background">
      <Header />
      <div className="flex">
        <Sidebar />
        <MainContent />
      </div>
    </div>
  );
}
