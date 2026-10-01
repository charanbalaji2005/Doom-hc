import * as React from 'react';
import { cva, type VariantProps } from 'class-variance-authority';
import { cn } from '@/lib/utils';

// shadcn/ui-pattern primitives, written by hand (the shadcn CLI was not run in this environment).
const buttonVariants = cva(
  'inline-flex items-center justify-center gap-1.5 rounded-md text-sm font-medium transition-colors disabled:pointer-events-none disabled:opacity-50 cursor-pointer',
  {
    variants: {
      variant: {
        default: 'bg-emerald text-graphite-950 hover:bg-emerald/90',
        secondary: 'bg-graphite-800 text-ceramic hover:bg-graphite-700 border border-graphite-700',
        ghost: 'text-graphite-300 hover:bg-graphite-800 hover:text-ceramic',
        danger: 'bg-danger text-white hover:bg-danger/90',
      },
      size: { default: 'h-9 px-3', sm: 'h-7 px-2 text-xs', icon: 'h-9 w-9' },
    },
    defaultVariants: { variant: 'default', size: 'default' },
  },
);

export interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement>, VariantProps<typeof buttonVariants> {}
export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(({ className, variant, size, ...props }, ref) => (
  <button ref={ref} className={cn(buttonVariants({ variant, size }), className)} {...props} />
));
Button.displayName = 'Button';

export const Input = React.forwardRef<HTMLInputElement, React.InputHTMLAttributes<HTMLInputElement>>(({ className, ...props }, ref) => (
  <input ref={ref} className={cn('h-9 w-full rounded-md border border-graphite-700 bg-graphite-950 px-3 text-sm placeholder:text-graphite-500', className)} {...props} />
));
Input.displayName = 'Input';

export function Field({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <label className="block space-y-1">
      <span className="text-sm text-ceramic">{label}</span>
      {children}
      {hint && <span className="block text-xs text-graphite-500">{hint}</span>}
    </label>
  );
}
