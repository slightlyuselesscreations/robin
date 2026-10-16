import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Fingerprint, KeyRound, LogIn } from 'lucide-react'
import { useEffect, useState } from 'react'

import { CodeInput } from '@/components/CodeInput'
import { Field, FlyingLogo, Notice, PanelBody, Section } from '@/components/Page'
import { Button } from '@/components/ui/button'
import { FieldError, FieldSeparator } from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import { Spinner } from '@/components/ui/spinner'
import { SIGNED_OUT, api, cancelled, passkeysSupported, signedOut, errorText } from '@/lib/api'
import { riseAt } from '@/lib/motion'
import { INPUT } from '@/lib/utils'

/** Nothing below renders, and so nothing asks the API, until the backend lets this browser in. */
export function AuthGate({ children }: { children: React.ReactNode }) {
  const client = useQueryClient()
  const me = useQuery({ queryKey: ['me'], queryFn: api.me, staleTime: Infinity })

  useEffect(() => {
    const onSignedOut = () => signedOut(client)
    window.addEventListener(SIGNED_OUT, onSignedOut)
    return () => window.removeEventListener(SIGNED_OUT, onSignedOut)
  }, [client])

  if (me.isPending) {
    return (
      <Screen>
        <Spinner className="mx-auto size-8 text-ink-dim" />
      </Screen>
    )
  }
  if (me.isError) {
    return (
      <Screen>
        <Notice tone="bad">Robin is not answering.</Notice>
      </Screen>
    )
  }
  if (!me.data.signed_in) return <SignIn />
  if (me.data.one_time) return <Claim username={me.data.username} />
  return children
}

/** Signing in, the robin in flight over its welcome. A first visit says where the password is. */
function Screen({ first = false, children }: { first?: boolean; children: React.ReactNode }) {
  return (
    <div className="flex min-h-svh items-center justify-center bg-base px-4">
      <div className="w-full max-w-sm space-y-6">
        <div className="flex flex-col items-center gap-2 text-center">
          <FlyingLogo />
          <h1 className="rise text-2xl font-semibold tracking-tight text-ink" style={riseAt(0)}>
            Welcome to <span className="text-accent">Robin</span>!
          </h1>
          <p className="rise text-sm text-ink-dim" style={riseAt(1)}>
            Your personal entertainment tracker and manager
          </p>
        </div>
        <div className="space-y-3">
          {first ? (
            <div className="rise space-y-1 pt-4 text-center text-xs" style={riseAt(2)}>
              <p className="text-ink">Please sign in with the pre-generated password</p>
              <p className="text-ink-faint">
                If you haven't read the instructions, you will find it in the container's logs ;)
              </p>
            </div>
          ) : null}
          {children}
        </div>
      </div>
    </div>
  )
}

function Failure({ error }: { error: unknown }) {
  if (!error || cancelled(error)) return null
  return <FieldError className="text-xs">{errorText(error, 'Something went wrong')}</FieldError>
}

/** Signed in with the one-time password, which only sets another. */
function Claim({ username: current }: { username: string }) {
  const client = useQueryClient()
  const [username, setUsername] = useState(current)
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const mismatch = confirm !== '' && confirm !== password

  const setup = useMutation({
    mutationFn: () => api.claim(username, password),
    onSuccess: () => client.invalidateQueries({ queryKey: ['me'] }),
  })

  return (
    <Screen>
      <Section title="Set a new password" icon={KeyRound}>
        <PanelBody>
          <form
            className="space-y-5"
            onSubmit={(e) => {
              e.preventDefault()
              setup.mutate()
            }}
          >
            <Field id="username" label="Username">
              <Input
                id="username"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                autoComplete="username"
                className={INPUT}
              />
            </Field>
            <Field id="password" label="Password">
              <Input
                id="password"
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                autoComplete="new-password"
                minLength={8}
                autoFocus
                className={INPUT}
              />
            </Field>
            <Field id="confirm" label="Password again">
              <Input
                id="confirm"
                type="password"
                value={confirm}
                onChange={(e) => setConfirm(e.target.value)}
                autoComplete="new-password"
                className={INPUT}
              />
            </Field>
            {mismatch ? <FieldError className="text-xs">The passwords differ</FieldError> : null}
            <Failure error={setup.error} />
            <Button
              type="submit"
              disabled={
                setup.isPending || !username.trim() || password.length < 8 || confirm !== password
              }
            >
              {setup.isPending ? <Spinner className="size-4" /> : <KeyRound className="size-4" />}
              Set password
            </Button>
          </form>
        </PanelBody>
      </Section>
    </Screen>
  )
}

function SignIn() {
  const client = useQueryClient()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [code, setCode] = useState('')
  const [needsCode, setNeedsCode] = useState(false)

  const me = useQuery({ queryKey: ['me'], queryFn: api.me, staleTime: Infinity })
  const offerPasskey = passkeysSupported && me.data?.passkeys === true
  const first = me.data?.one_time === true

  const login = useMutation({
    mutationFn: () => api.login(username, password, code),
    onSuccess: (result) => {
      if (result.needs_code) setNeedsCode(true)
      else void client.invalidateQueries({ queryKey: ['me'] })
    },
  })
  const passkey = useMutation({
    mutationFn: api.passkeyLogin,
    onSuccess: () => client.invalidateQueries({ queryKey: ['me'] }),
  })

  return (
    <Screen first={first}>
      <Section title="Sign in" icon={LogIn}>
        <PanelBody className="space-y-5">
          {offerPasskey ? (
            <>
              <Button
                variant="outline"
                className="w-full"
                onClick={() => passkey.mutate()}
                disabled={passkey.isPending}
              >
                {passkey.isPending ? (
                  <Spinner className="size-4" />
                ) : (
                  <Fingerprint className="size-4" />
                )}
                Sign in with a passkey
              </Button>
              <Failure error={passkey.error} />
              <FieldSeparator className="my-0 text-xs [&_[data-slot=field-separator-content]]:bg-surface">
                or
              </FieldSeparator>
            </>
          ) : null}
          <form
            className="space-y-5"
            onSubmit={(e) => {
              e.preventDefault()
              login.mutate()
            }}
          >
            <Field id="username" label="Username">
              <Input
                id="username"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                autoComplete="username"
                autoFocus
                className={INPUT}
              />
            </Field>
            <Field id="password" label="Password">
              <Input
                id="password"
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                autoComplete="current-password"
                className={INPUT}
              />
            </Field>
            {needsCode ? (
              <Field id="code" label="Code from your authenticator app">
                <CodeInput id="code" value={code} onChange={setCode} autoFocus />
              </Field>
            ) : null}
            <Failure error={login.error} />
            <Button
              type="submit"
              disabled={login.isPending || !username || !password || (needsCode && code.length < 6)}
            >
              {login.isPending ? <Spinner className="size-4" /> : <LogIn className="size-4" />}
              Sign in
            </Button>
          </form>
        </PanelBody>
      </Section>
    </Screen>
  )
}
