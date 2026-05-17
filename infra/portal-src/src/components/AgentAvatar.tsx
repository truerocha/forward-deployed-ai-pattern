/**
 * AgentAvatar — Visual identity for AI agents using Cloudscape design tokens.
 *
 * Renders a circular avatar with initials and role-specific color.
 * Follows Cloudscape Avatar pattern (https://cloudscape.design/components/avatar/)
 * using available design tokens for consistency.
 *
 * Roles:
 *   - Orchestrator: 🎯 blue (primary coordinator)
 *   - Pesquisa (Research): 🔍 teal (information gathering)
 *   - Escrita (Writing): ✍️ green (code generation)
 *   - Revisao (Review): 🔎 orange (quality validation)
 *   - ERP Executor: ⚡ purple (step execution)
 *   - System: ⚙️ grey (infrastructure events)
 */
import React from 'react';

interface AgentAvatarProps {
  agentName: string;
  size?: 's' | 'm' | 'l';
}

interface AvatarConfig {
  initials: string;
  bgColor: string;
  textColor: string;
  icon: string;
}

function getAvatarConfig(agentName: string): AvatarConfig {
  const name = agentName.toLowerCase();

  if (name.includes('orchestrat') || name.includes('conductor') || name.includes('squad')) {
    return { initials: 'OR', bgColor: '#0972d3', textColor: '#ffffff', icon: '🎯' };
  }
  if (name.includes('pesquisa') || name.includes('research') || name.includes('reconn')) {
    return { initials: 'PQ', bgColor: '#037f8c', textColor: '#ffffff', icon: '🔍' };
  }
  if (name.includes('escrita') || name.includes('writ') || name.includes('engineer')) {
    return { initials: 'ES', bgColor: '#037f0c', textColor: '#ffffff', icon: '✍️' };
  }
  if (name.includes('revisao') || name.includes('review') || name.includes('quality')) {
    return { initials: 'RV', bgColor: '#d97706', textColor: '#ffffff', icon: '🔎' };
  }
  if (name.includes('erp') || name.includes('step') || name.includes('execut')) {
    return { initials: 'EX', bgColor: '#7c3aed', textColor: '#ffffff', icon: '⚡' };
  }
  if (name.includes('system') || name.includes('reaper') || name.includes('infra')) {
    return { initials: 'SY', bgColor: '#5f6b7a', textColor: '#ffffff', icon: '⚙️' };
  }
  // Default: use first 2 chars
  const initials = agentName.slice(0, 2).toUpperCase();
  return { initials, bgColor: '#414d5c', textColor: '#ffffff', icon: '🤖' };
}

const SIZES = { s: 24, m: 32, l: 40 };

export const AgentAvatar: React.FC<AgentAvatarProps> = ({ agentName, size = 'm' }) => {
  const config = getAvatarConfig(agentName);
  const px = SIZES[size];

  return (
    <span
      title={`${config.icon} ${agentName}`}
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        justifyContent: 'center',
        width: px,
        height: px,
        borderRadius: '50%',
        backgroundColor: config.bgColor,
        color: config.textColor,
        fontSize: px * 0.4,
        fontWeight: 700,
        lineHeight: 1,
        flexShrink: 0,
      }}
    >
      {config.initials}
    </span>
  );
};

export { getAvatarConfig };
